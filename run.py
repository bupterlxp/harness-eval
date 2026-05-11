#!/usr/bin/env python3
"""
Harness Eval Runner

Reads tasks from a JSONL file, spins up Docker containers with Claude Code + ccr,
and collects the outputs.

Each task in the JSONL supports three modes:
  - "prompt":      inline prompt text → written as CLAUDE.md
  - "prompt_file": path to a .md file → copied as CLAUDE.md
  - "task_dir":    directory containing CLAUDE.md and supporting files

Optional "files" field: {"dest_path": "src_path"} to copy extra materials into workspace.
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


def prepare_workspace(task: dict, workspace: str):
    ws = Path(workspace)

    if "task_dir" in task:
        task_dir = Path(task["task_dir"])
        if not task_dir.is_dir():
            raise FileNotFoundError(f"task_dir not found: {task_dir}")
        for item in task_dir.iterdir():
            dest = ws / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
        if not (ws / "CLAUDE.md").exists():
            raise FileNotFoundError(f"CLAUDE.md not found in {task_dir}")

    elif "prompt_file" in task:
        prompt_path = Path(task["prompt_file"])
        if not prompt_path.is_file():
            raise FileNotFoundError(f"prompt_file not found: {prompt_path}")
        (ws / "CLAUDE.md").write_text(prompt_path.read_text(encoding="utf-8"))

    elif "prompt" in task:
        (ws / "CLAUDE.md").write_text(task["prompt"])

    else:
        raise ValueError(
            f"Task '{task.get('id', '?')}' must have 'prompt', 'prompt_file', or 'task_dir'"
        )

    if "files" in task:
        file_map = task["files"]
        if isinstance(file_map, dict):
            items = file_map.items()
        else:
            raise ValueError(f"'files' must be a dict, got {type(file_map).__name__}")

        for dest_rel, src_rel in items:
            src = Path(src_rel)
            dest = ws / dest_rel
            if not src.exists():
                raise FileNotFoundError(f"files source not found: {src}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dest)
            else:
                shutil.copy2(src, dest)


def run_task(task: dict, config: dict, output_dir: Path) -> dict:
    task_id = task["id"]
    task_output_dir = output_dir / task_id
    task_output_dir.mkdir(parents=True, exist_ok=True)

    workspace_base = Path.home() / ".harness-eval" / "workspaces"
    workspace_base.mkdir(parents=True, exist_ok=True)
    workspace = tempfile.mkdtemp(prefix=f"harness_{task_id}_", dir=str(workspace_base))

    try:
        prepare_workspace(task, workspace)
    except (FileNotFoundError, KeyError, ValueError) as e:
        meta = {"task_id": task_id, "status": "error", "stdout": "", "stderr": str(e)}
        (task_output_dir / "meta.json").write_text(json.dumps(meta, indent=2))
        shutil.rmtree(workspace, ignore_errors=True)
        print(f"[{task_id}] error preparing workspace: {e}")
        return meta

    container_name = f"harness-eval-{task_id}-{int(time.time())}"
    timeout = config.get("timeout_minutes", 30) * 60

    try:
        result = subprocess.run(
            [
                "docker", "run",
                "--name", container_name,
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
        subprocess.run(["docker", "stop", "-t", "5", container_name], capture_output=True)
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
    except Exception as e:
        status = "error"
        stdout = ""
        stderr = str(e)

    # Remove the container if it still exists (no --rm flag)
    subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)

    for item in Path(workspace).iterdir():
        dest = task_output_dir / item.name
        if item.is_dir():
            if item.name == ".git":
                continue
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)

    meta = {
        "task_id": task_id,
        "status": status,
        "stdout": stdout[-5000:] if stdout else "",
        "stderr": stderr[-5000:] if stderr else "",
    }
    (task_output_dir / "meta.json").write_text(json.dumps(meta, indent=2))

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
    print(f"Running {len(tasks)} task(s) with max {max_concurrent} concurrent containers...")

    results = []
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        futures = {
            executor.submit(run_task, task, config, output_dir): task
            for task in tasks
        }
        for future in as_completed(futures):
            results.append(future.result())

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
