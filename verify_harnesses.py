#!/usr/bin/env python3
"""Verify generated harnesses meet minimum quality requirements."""
import json
import os
import sys
from pathlib import Path


def check_harness(harness_dir: Path, harness_type: str) -> dict:
    """Check a single generated harness for quality criteria."""
    results = {
        "harness_type": harness_type,
        "dir": str(harness_dir),
        "checks": {},
    }

    # Find all Python files
    py_files = list(harness_dir.rglob("*.py"))
    all_py_content = ""
    for f in py_files:
        try:
            all_py_content += f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # Check 1: Has Python files
    results["checks"]["has_python_files"] = len(py_files) > 0

    # Check 2: Has __main__.py in harness/
    main_files = [f for f in py_files if f.name == "__main__.py" and "harness" in str(f)]
    has_main = len(main_files) > 0
    # Also accept harness.py at root (some models do this)
    if not has_main:
        has_main = any(f.name == "harness.py" for f in py_files)
    results["checks"]["has_entry_point"] = has_main

    # Check 3: Uses openai SDK
    has_openai = "from openai import" in all_py_content or "import openai" in all_py_content
    results["checks"]["has_openai_sdk"] = has_openai

    # Check 4: Has tool calling pattern
    has_tools = "tool_calls" in all_py_content or "tool_choice" in all_py_content
    results["checks"]["has_tool_calling"] = has_tools

    # Check 5: Has LLM call
    has_llm_call = "chat.completions.create" in all_py_content
    results["checks"]["has_llm_call"] = has_llm_call

    # Check 6: Produces result.json
    has_result = "result.json" in all_py_content or '"status"' in all_py_content
    results["checks"]["has_result_output"] = has_result

    # Check 7: Produces trajectory
    has_trajectory = "trajectory" in all_py_content
    results["checks"]["has_trajectory"] = has_trajectory

    # Check 8: Has Dockerfile
    has_dockerfile = (harness_dir / "Dockerfile").exists()
    results["checks"]["has_dockerfile"] = has_dockerfile

    # Check 9: Has requirements.txt
    has_requirements = (harness_dir / "requirements.txt").exists()
    results["checks"]["has_requirements"] = has_requirements

    # Check 10: Has domain-specific tools
    domain_tools = {
        "code-agent-harness": ["read_file", "write_file", "run_command"],
        "data-analysis-harness": ["execute_python", "read_file"],
        "writing-harness": ["plan_outline", "write_section"],
        "research-agent-harness": ["search_web", "write_report"],
        "browser-agent-harness": ["navigate", "click"],
    }
    expected = domain_tools.get(harness_type, [])
    found = sum(1 for t in expected if t in all_py_content)
    results["checks"]["has_domain_tools"] = found >= len(expected) * 0.5  # at least half

    # Summary
    total = len(results["checks"])
    passed = sum(1 for v in results["checks"].values() if v)
    results["score"] = f"{passed}/{total}"
    results["passed"] = passed == total
    results["total_lines"] = sum(1 for _ in all_py_content.splitlines())

    return results


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 verify_harnesses.py <output_dir> [<output_dir2> ...]")
        sys.exit(1)

    for output_dir in sys.argv[1:]:
        output_path = Path(output_dir)
        if not output_path.exists():
            print(f"Directory not found: {output_dir}")
            continue

        print(f"\n{'='*60}")
        print(f"Model: {output_path.name}")
        print(f"{'='*60}")

        harness_dirs = sorted([d for d in output_path.iterdir() if d.is_dir()])

        total_pass = 0
        total_harnesses = 0

        for harness_dir in harness_dirs:
            if harness_dir.name in ("summary.json",):
                continue
            total_harnesses += 1
            result = check_harness(harness_dir, harness_dir.name)

            status = "PASS" if result["passed"] else "FAIL"
            if result["passed"]:
                total_pass += 1

            print(f"\n  {result['harness_type']}: {status} ({result['score']}, {result['total_lines']} lines)")
            for check, passed in result["checks"].items():
                mark = "+" if passed else "X"
                print(f"    [{mark}] {check}")

        print(f"\n  Overall: {total_pass}/{total_harnesses} harnesses passed")


if __name__ == "__main__":
    main()
