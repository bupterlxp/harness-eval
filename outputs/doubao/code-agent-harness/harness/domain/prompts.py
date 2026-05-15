#!/usr/bin/env python3
"""
Domain-specific prompts for bug analysis and fixing.
"""

BUG_ANALYSIS_PROMPT = """
You are an expert Python developer analyzing code for bugs. Given a code snippet and context,
identify the bug, classify it, and provide a fix.

File: {file_path}
Line: {line_number}

Code:
```python
{code_snippet}
```

Surrounding context:
```python
{surrounding_context}
```

Return a JSON object with exactly these fields:
{{
    "bug_type": "security|logic|performance|naming|typo|compatibility",
    "severity": "critical|high|medium|low",
    "title": "Short descriptive title (max 50 chars)",
    "description": "Detailed explanation of the bug",
    "fix_suggestion": "Exact code replacement for the buggy section",
    "affected_lines": "Range of lines affected (e.g., '45-50')"
}}
"""

COMMIT_MESSAGE_PROMPT = """
Generate a conventional commit message for this bug fix:

Bug ID: #{bug_id}
Title: {bug_title}
Description: {bug_description}

Follow conventional commits format. Return only the commit message, nothing else.
"""

FIX_VALIDATION_PROMPT = """
Review this fix for the given bug:

Bug Description: {bug_description}
Fix Applied:
```python
{fix_code}
```

Original Code:
```python
{original_code}
```

Check if the fix correctly addresses the bug. Return JSON with:
{{
    "valid": true/false,
    "confidence": 0-100,
    "explanation": "Reasoning about the fix",
    "suggestions": "Optional improvements"
}}
"""

TEST_COVERAGE_PROMPT = """
Analyze these test results and determine if they cover the bug fix:

Test Output:
{test_output}

Bug Fixed: {bug_description}

Return JSON with:
{{
    "covers_fix": true/false,
    "coverage_score": 0-100,
    "missing_tests": ["list of missing test cases"],
    "passing": true/false
}}
"""

# Bug type mappings from the spec
BUG_TYPE_MAPPING = {
    "sql_injection": BugType.SECURITY,
    "logic_error": BugType.LOGIC,
    "performance": BugType.PERFORMANCE,
    "naming": BugType.NAMING,
    "typo": BugType.TYPO,
    "compatibility": BugType.COMPATIBILITY
}

# Bug severity mappings
BUG_SEVERITY_MAPPING = {
    "critical": BugSeverity.CRITICAL,
    "high": BugSeverity.HIGH,
    "medium": BugSeverity.MEDIUM,
    "low": BugSeverity.LOW
}