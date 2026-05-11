#!/usr/bin/env python3
"""
Harness Eval Runner
Reads tasks from a JSONL file, spins up Docker containers with Claude Code,
and collects the outputs.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml


def load_config(config_path: str = "config.yaml") -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_tasks(tasks_file: str) -> list[dict]:
    tasks = []
    with open(tasks_file) as f:
        for line in f:
            line = line.strip()
            if line:
                tasks.append(json.loads(line))
    return tasks


def build_docker_image():
    print("Building Docker image...")
    subprocess.run(
        ["docker", "build", "-t", "harness-eval", "."],
        check=True,
    )
    print("Docker image built.")


def run_task(task: dict, config: dict, output_dir: Path) -> dict:
    task_id = task["id"]
    prompt = task["prompt"]
    task_output_dir = output_dir / task_id
    task_output_dir.mkdir(parents=True, exist_ok=True)

    # Create a temp dir for workspace mount
    workspace = tempfile.mkdtemp(prefix=f"harness_{task_id}_")

    # Write CLAUDE.md with the task prompt
    claude_md = Path(workspace) / "CLAUDE.md"
    claude_md.write_text(f"""# Task

You are an agent tasked with writing a harness. Follow the requirements below carefully.
Write all output files in the current directory (/workspace).

## Requirements

{prompt}
""")

    container_name = f"harness-eval-{task_id}-{int(time.time())}"
    timeout = config.get("timeout_minutes", 30) * 60

    try:
        result = subprocess.run(
            [
                "docker", "run",
                "--name", container_name,
                "--rm",
                "-e", f"BASE_URL={config['base_url']}",
                "-e", f"API_KEY={config['api_key']}",
                "-e", f"MODEL_NAME={config['model_name']}",
                "-v", f"{workspace}:/workspace",
                "harness-eval",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        status = "success" if result.returncode == 0 else "failed"
        stdout = result.stdout
        stderr = result.stderr
    except subprocess.TimeoutExpired:
        status = "timeout"
        stdout = ""
        stderr = "Task timed out"
        subprocess.run(["docker", "kill", container_name], capture_output=True)
    except Exception as e:
        status = "error"
        stdout = ""
        stderr = str(e)

    # Copy workspace outputs to output dir
    for item in Path(workspace).iterdir():
        dest = task_output_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)

    # Write metadata
    meta = {
        "task_id": task_id,
        "status": status,
        "stdout": stdout[-2000:] if stdout else "",
        "stderr": stderr[-2000:] if stderr else "",
    }
    (task_output_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    # Cleanup temp workspace
    shutil.rmtree(workspace, ignore_errors=True)

    print(f"[{task_id}] {status}")
    return meta


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    config = load_config(config_path)

    tasks = load_tasks(config.get("tasks_file", "tasks.jsonl"))
    if not tasks:
        print("No tasks found.")
        return

    output_dir = Path(config.get("output_dir", "./outputs"))
    output_dir.mkdir(parents=True, exist_ok=True)

    build_docker_image()

    max_concurrent = config.get("max_concurrent", 4)
    print(f"Running {len(tasks)} tasks with max {max_concurrent} concurrent containers...")

    results = []
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        futures = {
            executor.submit(run_task, task, config, output_dir): task
            for task in tasks
        }
        for future in as_completed(futures):
            results.append(future.result())

    # Summary
    summary = {
        "total": len(results),
        "success": sum(1 for r in results if r["status"] == "success"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "timeout": sum(1 for r in results if r["status"] == "timeout"),
        "error": sum(1 for r in results if r["status"] == "error"),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nDone. Summary: {summary}")


if __name__ == "__main__":
    main()
