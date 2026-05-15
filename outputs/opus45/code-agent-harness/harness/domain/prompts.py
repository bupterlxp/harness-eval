"""
LLM prompts for bug analysis, fix generation, and commit messages.

Uses OpenAI-compatible API via environment variables:
- OPENAI_BASE_URL: API endpoint
- OPENAI_API_KEY: API key
- MODEL_NAME: Model identifier
"""

import os
from typing import Optional

from openai import OpenAI

from harness.schemas import BugReport, BugCategory, BugSeverity


def get_client() -> OpenAI:
    """Get OpenAI client configured from environment."""
    return OpenAI(
        base_url=os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:3457/v1"),
        api_key=os.environ.get("OPENAI_API_KEY", "dummy"),
    )


def get_model() -> str:
    """Get model name from environment."""
    return os.environ.get("MODEL_NAME", "gpt-4")


def analyze_bug(
    code_context: str,
    test_failure: str,
    file_path: str,
    line_hint: Optional[int] = None,
) -> dict:
    """
    Analyze a bug from test failure and code context.

    Returns dict with:
    - root_cause: Description of the root cause
    - category: Bug category (security, correctness, etc.)
    - severity: Bug severity
    - fix_suggestion: Suggested fix approach
    """
    prompt = f"""Analyze this bug based on the test failure and code context.

## Test Failure
```
{test_failure}
```

## Code Context ({file_path}{f', around line {line_hint}' if line_hint else ''})
```python
{code_context}
```

Respond in JSON format:
{{
    "root_cause": "Brief description of why this bug occurs",
    "category": "security|correctness|logic|timing|validation|spec",
    "severity": "critical|high|medium|low",
    "fix_suggestion": "Specific code change needed to fix this"
}}

Focus on:
- Security bugs (SQL injection, etc.) should be marked critical
- Timing issues (using closed connections, race conditions) are high severity
- Logic errors that cause wrong results are high severity
- Spec violations (wrong status codes) are medium severity
"""

    client = get_client()
    response = client.chat.completions.create(
        model=get_model(),
        messages=[
            {"role": "system", "content": "You are a code analysis expert. Respond only with valid JSON."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
    )

    import json
    try:
        return json.loads(response.choices[0].message.content)
    except json.JSONDecodeError:
        return {
            "root_cause": "Unable to parse analysis",
            "category": "correctness",
            "severity": "medium",
            "fix_suggestion": "Manual analysis required",
        }


def generate_fix(
    bug: BugReport,
    code_context: str,
    test_failure: str,
    previous_attempts: list[dict] = None,
) -> dict:
    """
    Generate a fix for a bug.

    Returns dict with:
    - old_code: The code to replace
    - new_code: The replacement code
    - explanation: Why this fix works
    """
    attempts_context = ""
    if previous_attempts:
        attempts_context = "\n## Previous Failed Attempts\n"
        for i, attempt in enumerate(previous_attempts, 1):
            attempts_context += f"\nAttempt {i}:\n```\n{attempt.get('diff', 'N/A')}\n```\nError: {attempt.get('error', 'N/A')}\n"

    prompt = f"""Fix this bug. Provide the exact code replacement needed.

## Bug Description
- ID: {bug.id}
- Title: {bug.title}
- Category: {bug.category.value}
- Severity: {bug.severity.value}
- Root Cause: {bug.root_cause or 'Unknown'}
- Location: {bug.file_path}:{bug.line_number}

## Test Failure
```
{test_failure}
```

## Code Context
```python
{code_context}
```
{attempts_context}

Respond in JSON format:
{{
    "old_code": "exact code to replace (copy from context)",
    "new_code": "fixed code",
    "explanation": "why this fix addresses the root cause"
}}

IMPORTANT:
- old_code must exactly match existing code (including whitespace)
- new_code should be minimal - only change what's necessary
- Do not add unnecessary comments or refactoring
"""

    client = get_client()
    response = client.chat.completions.create(
        model=get_model(),
        messages=[
            {"role": "system", "content": "You are a code fixing expert. Respond only with valid JSON."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
    )

    import json
    try:
        return json.loads(response.choices[0].message.content)
    except json.JSONDecodeError:
        return {
            "old_code": "",
            "new_code": "",
            "explanation": "Unable to generate fix",
        }


def generate_commit_message(
    bug: BugReport,
    diff: str,
) -> str:
    """
    Generate a commit message for a bug fix.

    Returns a well-formatted commit message.
    """
    prompt = f"""Generate a git commit message for this bug fix.

## Bug
- ID: {bug.id}
- Title: {bug.title}
- Category: {bug.category.value}
- Root Cause: {bug.root_cause or 'See diff'}

## Diff
```
{diff}
```

Write a commit message following this format:
```
fix(<scope>): <short description>

<longer description of what was wrong and how it was fixed>

Bug-ID: {bug.id}
```

Keep it concise but informative. The first line should be under 72 characters.
"""

    client = get_client()
    response = client.chat.completions.create(
        model=get_model(),
        messages=[
            {"role": "system", "content": "You are a git commit message expert. Write clear, conventional commits."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
    )

    return response.choices[0].message.content.strip()


def classify_test_failures(
    test_output: str,
    source_file: str,
) -> list[dict]:
    """
    Classify test failures into potential bugs.

    Returns list of dicts with:
    - test_name: Name of failing test
    - likely_line: Suspected line number in source
    - category: Suspected bug category
    - description: Brief description
    """
    prompt = f"""Analyze these test failures and classify them by likely root cause.

## Test Output
```
{test_output}
```

## Source File
{source_file}

For each distinct failure, provide:
{{
    "failures": [
        {{
            "test_name": "test name",
            "likely_line": line_number_or_null,
            "category": "security|correctness|logic|timing|validation|spec",
            "description": "brief description of what's wrong"
        }}
    ]
}}

Group related failures (same root cause) together.
"""

    client = get_client()
    response = client.chat.completions.create(
        model=get_model(),
        messages=[
            {"role": "system", "content": "You are a test analysis expert. Respond only with valid JSON."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
    )

    import json
    try:
        result = json.loads(response.choices[0].message.content)
        return result.get("failures", [])
    except json.JSONDecodeError:
        return []


def suggest_related_tests(
    bug: BugReport,
    test_file_content: str,
) -> list[str]:
    """
    Suggest which tests to run for a specific bug.

    Returns list of test names/patterns.
    """
    prompt = f"""Given this bug and test file, identify which tests are most relevant.

## Bug
- Title: {bug.title}
- Category: {bug.category.value}
- File: {bug.file_path}
- Line: {bug.line_number}

## Test File
```python
{test_file_content}
```

List the test function names that would verify this bug is fixed.
Respond as a JSON array of test names:
["test_name1", "test_name2"]
"""

    client = get_client()
    response = client.chat.completions.create(
        model=get_model(),
        messages=[
            {"role": "system", "content": "You are a test expert. Respond only with a JSON array."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
    )

    import json
    try:
        return json.loads(response.choices[0].message.content)
    except json.JSONDecodeError:
        return []
