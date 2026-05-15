"""
Domain-specific tools and prompts for bug analysis.
"""

import json
import os
import subprocess
from typing import List, Dict, Any, Optional, Tuple
from openai import OpenAI

from ..schemas import BugReport, BugSeverity, BugType


class BugAnalyzer:
    """Analyzes code to identify and classify bugs."""

    def __init__(self, model: str = "gpt-3.5-turbo"):
        self.client = OpenAI(
            base_url=os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:3457/v1"),
            api_key=os.environ.get("OPENAI_API_KEY", "test_key")
        )
        self.model = model or os.environ.get("MODEL_NAME", "gpt-3.5-turbo")

    def analyze_bug(self, file_path: str, line_number: int, code_snippet: str) -> Dict[str, Any]:
        """Analyze a specific bug location."""
        prompt = f"""
        Analyze this code snippet and identify the bug:
        File: {file_path}
        Line: {line_number}
        Code:
        ```python
        {code_snippet}
        ```

        Return a JSON object with:
        - bug_type: security|logic|performance|naming|typo|compatibility
        - severity: critical|high|medium|low
        - title: short descriptive title
        - description: detailed description of the bug
        - fix_suggestion: suggested fix
        """

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}]
        )

        content = response.choices[0].message.content
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {
                "bug_type": "unknown",
                "severity": "medium",
                "title": "Unknown bug",
                "description": f"Could not analyze bug: {content}",
                "fix_suggestion": ""
            }


def detect_sql_injection(file_path: str) -> List[Tuple[int, str]]:
    """Detect potential SQL injection vulnerabilities."""
    vulnerabilities = []
    import ast

    try:
        with open(file_path, 'r') as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr == "execute":
                    if len(node.args) > 0:
                        if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                            sql = node.args[0].value
                            # Look for string formatting or f-strings
                            if "%" in sql or "f" in ast.dump(node.args[0]):
                                vulnerabilities.append((node.lineno, sql))
    except Exception:
        pass

    return vulnerabilities


def generate_commit_message(bug_id: int, title: str, description: str) -> str:
    """Generate a conventional commit message."""
    prompt = f"""
    Generate a conventional commit message for fixing bug #{bug_id}:
    Title: {title}
    Description: {description}

    Return just the commit message without any extra formatting.
    """

    client = OpenAI(
        base_url=os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:3457/v1"),
        api_key=os.environ.get("OPENAI_API_KEY", "test_key")
    )

    response = client.chat.completions.create(
        model=os.environ.get("MODEL_NAME", "gpt-3.5-turbo"),
        messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content.strip()


def apply_fix(file_path: str, old_string: str, new_string: str) -> bool:
    """Apply a fix to a file."""
    try:
        with open(file_path, 'r') as f:
            content = f.read()

        if old_string not in content:
            return False

        new_content = content.replace(old_string, new_string, 1)

        with open(file_path, 'w') as f:
            f.write(new_content)

        return True
    except Exception:
        return False