#!/usr/bin/env python3
"""
Run generated harnesses against downstream test tasks.

Usage:
    python3 test_harness.py <harness_dir> <task_id> [--model-config config.yaml]

Example:
    python3 test_harness.py outputs/glm51/code-agent-harness test-code --model-config config_glm51.yaml
    python3 test_harness.py outputs/doubao_v3/writing-harness test-writing --model-config config_doubao_code_test.yaml
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml


def load_test_tasks(tasks_file: str = "test_tasks/tasks.jsonl") -> dict:
    tasks = {}
    with open(tasks_file) as f:
        for line in f:
            line = line.strip()
            if line:
                t = json.loads(line)
                tasks[t["id"]] = t
    return tasks


def build_harness_image(harness_dir: Path, image_name: str) -> bool:
    """Build Docker image from generated harness."""
    print(f"  Building Docker image '{image_name}' from {harness_dir}...")
    result = subprocess.run(
        ["docker", "build", "-t", image_name, str(harness_dir)],
        capture_output=True, text=True, timeout=600,
    )
    if result.returncode != 0:
        print(f"  BUILD FAILED:\n{result.stderr[-500:]}")
        return False
    print("  Build OK.")
    return True


def run_harness_on_task(
    image_name: str,
    task: dict,
    model_config: dict,
    timeout_sec: int = 300,
) -> dict:
    """Run a harness container on a test task."""
    task_id = task["id"]
    prompt = task["prompt"]

    # Fix base_url for direct openai SDK usage
    # The config base_url may include /endpoints/chat/completions which is the full endpoint
    # OpenAI SDK needs just the base (it appends /chat/completions itself)
    base_url = model_config['base_url']
    if '/endpoints/chat/completions' in base_url:
        base_url = base_url.replace('/endpoints/chat/completions', '')

    # Create temp workspace with task files
    workspace = tempfile.mkdtemp(prefix=f"test_{task_id}_", dir=str(Path.home() / ".harness-eval" / "test_workspaces"))
    ws = Path(workspace)    # Copy task files into workspace
    if "files" in task:
        for dest_name, src_path in task["files"].items():
            src = Path(src_path)
            dest = ws / dest_name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dest)
            else:
                shutil.copy2(src, dest)

    # Create output dir in workspace
    output_dir = ws / "output"
    output_dir.mkdir()

    container_name = f"test-harness-{task_id}-{int(time.time())}"

    # Build the command with prompt
    cmd = [
        "docker", "run", "--rm",
        "--name", container_name,
        "-e", f"OPENAI_BASE_URL={base_url}",
        "-e", f"OPENAI_API_KEY={model_config['api_key']}",
        "-e", f"MODEL_NAME={model_config['model_name']}",
        "-e", "PYTHONPATH=/app",
        "-v", f"{workspace}:/workspace",
        "-w", "/workspace",
        image_name,
        "-p", prompt,
        "--output-dir", "/workspace/output",
    ]

    print(f"  Running harness on task '{task_id}'...")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_sec,
        )
        status = "success" if result.returncode == 0 else "failed"
        stdout = result.stdout
        stderr = result.stderr
    except subprocess.TimeoutExpired:
        status = "timeout"
        stdout = ""
        stderr = "Timed out"
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)

    # Collect results
    results = {
        "task_id": task_id,
        "container_status": status,
        "stdout": stdout[-2000:] if stdout else "",
        "stderr": stderr[-2000:] if stderr else "",
    }

    # Check result.json
    result_file = ws / "output" / "result.json"
    if result_file.exists():
        try:
            result_data = json.loads(result_file.read_text())
            results["harness_status"] = result_data.get("status", "unknown")
        except json.JSONDecodeError:
            results["harness_status"] = "invalid_json"
    else:
        results["harness_status"] = "no_result_file"

    # Check trajectory
    traj_file = ws / "output" / "trajectory.jsonl"
    if traj_file.exists():
        lines = traj_file.read_text().strip().split("\n")
        results["trajectory_steps"] = len(lines)
        # Parse actions
        actions = []
        for line in lines:
            try:
                entry = json.loads(line)
                actions.append(entry.get("action", "unknown"))
            except json.JSONDecodeError:
                pass
        results["actions"] = actions
    else:
        results["trajectory_steps"] = 0
        results["actions"] = []

    # Domain-specific checks
    results["domain_checks"] = check_domain_output(task_id, ws)

    # Copy output for inspection
    output_save = Path(f"test_results/{task_id}")
    output_save.mkdir(parents=True, exist_ok=True)
    for item in ws.iterdir():
        dest = output_save / item.name
        try:
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
        except Exception:
            pass

    # Cleanup
    shutil.rmtree(workspace, ignore_errors=True)

    return results


def check_domain_output(task_id: str, workspace: Path) -> dict:
    """Domain-specific output validation."""
    checks = {}

    if task_id == "test-code":
        # Check if app.py was modified (bugs fixed)
        app_py = workspace / "app.py"
        if app_py.exists():
            content = app_py.read_text()
            checks["bug1_fixed"] = "todo.id == todo_id" in content
            checks["bug2_fixed"] = "not t.completed" in content or "t.completed == False" in content or "not todo.completed" in content
        else:
            checks["bug1_fixed"] = False
            checks["bug2_fixed"] = False

    elif task_id == "test-data":
        checks["has_chart"] = any(workspace.rglob("*.png"))
        checks["has_report"] = (workspace / "REPORT.md").exists() or (workspace / "output" / "REPORT.md").exists()

    elif task_id == "test-writing":
        story_paths = list(workspace.rglob("story.md"))
        if story_paths:
            content = story_paths[0].read_text()
            word_count = len(content.split())
            checks["story_exists"] = True
            checks["word_count"] = word_count
            checks["has_enough_words"] = word_count >= 400
        else:
            checks["story_exists"] = False
            checks["word_count"] = 0
            checks["has_enough_words"] = False

    elif task_id == "test-research":
        report_paths = list(workspace.rglob("report.md"))
        if report_paths:
            content = report_paths[0].read_text()
            checks["report_exists"] = True
            checks["has_aws"] = "aws" in content.lower()
            checks["has_azure"] = "azure" in content.lower()
            checks["has_gcp"] = "gcp" in content.lower() or "google cloud" in content.lower()
            checks["word_count"] = len(content.split())
        else:
            checks["report_exists"] = False

    elif task_id == "test-browser":
        product_paths = list(workspace.rglob("products.json"))
        if product_paths:
            try:
                products = json.loads(product_paths[0].read_text())
                checks["products_extracted"] = True
                checks["product_count"] = len(products) if isinstance(products, list) else 0
            except json.JSONDecodeError:
                checks["products_extracted"] = False
        else:
            checks["products_extracted"] = False

    return checks


def print_results(results: dict):
    """Pretty print test results."""
    task_id = results["task_id"]
    print(f"\n{'='*50}")
    print(f"Task: {task_id}")
    print(f"{'='*50}")
    print(f"  Container: {results['container_status']}")
    print(f"  Harness status: {results['harness_status']}")
    print(f"  Trajectory steps: {results['trajectory_steps']}")

    if results['actions']:
        action_summary = {}
        for a in results['actions']:
            action_summary[a] = action_summary.get(a, 0) + 1
        print(f"  Actions: {dict(action_summary)}")

    if results['domain_checks']:
        print(f"  Domain checks:")
        for k, v in results['domain_checks'].items():
            mark = "+" if v else "X"
            if isinstance(v, bool):
                print(f"    [{mark}] {k}")
            else:
                print(f"    [i] {k}: {v}")

    if results.get('stderr') and results['container_status'] != 'success':
        print(f"  Stderr (last 300): {results['stderr'][-300:]}")


def main():
    parser = argparse.ArgumentParser(description="Test generated harnesses on downstream tasks")
    parser.add_argument("harness_dir", help="Path to generated harness directory")
    parser.add_argument("task_id", help="Test task ID (e.g. test-code)")
    parser.add_argument("--model-config", default="config_glm51.yaml",
                        help="Model config YAML for LLM access")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Timeout in seconds")
    parser.add_argument("--all", action="store_true",
                        help="Run all compatible tasks")
    args = parser.parse_args()

    # Load model config
    with open(args.model_config) as f:
        model_config = yaml.safe_load(f)

    # Load test tasks
    test_tasks = load_test_tasks()

    harness_dir = Path(args.harness_dir)
    if not harness_dir.exists():
        print(f"Error: {harness_dir} not found")
        sys.exit(1)

    # Build image
    harness_name = harness_dir.name
    image_name = f"test-harness-{harness_name}"
    if not build_harness_image(harness_dir, image_name):
        sys.exit(1)

    # Run task(s)
    if args.task_id not in test_tasks:
        print(f"Error: task '{args.task_id}' not found. Available: {list(test_tasks.keys())}")
        sys.exit(1)

    task = test_tasks[args.task_id]
    results = run_harness_on_task(image_name, task, model_config, args.timeout)
    print_results(results)


if __name__ == "__main__":
    main()
