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
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from creation_eval.model_aliases import (
    BUILTIN_CODEX_MODEL_ALIASES,
    BUILTIN_MODEL_ALIASES,
    merged_model_aliases,
    resolve_codex_model_alias,
    resolve_model_alias,
)


def default_config() -> dict:
    return {
        "base_url": os.environ.get("BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "",
        "api_key": os.environ.get("API_KEY") or os.environ.get("OPENAI_API_KEY") or "",
        "model_name": os.environ.get("MODEL_NAME") or "",
        "claude_model_name": os.environ.get("CLAUDE_MODEL_NAME", "claude-sonnet-4-6"),
        "reasoning_effort": os.environ.get("REASONING_EFFORT"),
        "eval_base_url": os.environ.get("EVAL_BASE_URL") or "",
        "eval_api_key": os.environ.get("EVAL_API_KEY") or "",
        "eval_model_name": os.environ.get("EVAL_MODEL_NAME") or "",
        "eval_reasoning_effort": os.environ.get("EVAL_REASONING_EFFORT") or "",
        "meta_harness": "claude-code",
        "model_aliases": {},
        "codex_model_aliases": {},
        "codex_bin": os.environ.get("CODEX_BIN", "codex"),
        "codex_sandbox": os.environ.get("CODEX_SANDBOX", "workspace-write"),
        "codex_enable_search": False,
        "codex_extra_args": "",
        "max_concurrent": 1,
        "timeout_minutes": 30,
        "workspace_dir": "/workspace",
        "output_dir": "./outputs",
        "tasks_file": "./tasks.jsonl",
        "system_prompt_file": "./prompts/system_prompt.md",
        "include_system_prompt": True,
        "creation_profile": os.environ.get("CREATION_PROFILE", "interface_tool"),
        "creation_profile_dir": "./prompts/creation/profiles",
        "pre_bmk_gate": os.environ.get("PRE_BMK_GATE", "soft"),
    }


def load_config(config_path: str = "config.yaml") -> dict:
    config = default_config()
    path = Path(config_path)
    if not path.exists():
        if config_path != "config.yaml":
            raise FileNotFoundError(f"config file not found: {config_path}")
        return config

    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(text) or {}
        config.update(loaded)
        return config
    except ModuleNotFoundError:
        for raw_line in text.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            value = value.strip().strip("'\"")
            if value.isdigit():
                config[key.strip()] = int(value)
            elif value.lower() in {"true", "false"}:
                config[key.strip()] = value.lower() == "true"
            else:
                config[key.strip()] = value
        return config


def apply_cli_overrides(config: dict, args: argparse.Namespace) -> dict:
    override_fields = {
        "base_url": args.base_url,
        "api_key": args.api_key,
        "model_name": args.model_name,
        "claude_model_name": args.claude_model_name,
        "reasoning_effort": args.reasoning_effort,
        "eval_base_url": args.eval_base_url,
        "eval_api_key": args.eval_api_key,
        "eval_model_name": args.eval_model_name,
        "eval_reasoning_effort": args.eval_reasoning_effort,
        "meta_harness": args.meta_harness,
        "codex_bin": args.codex_bin,
        "codex_sandbox": args.codex_sandbox,
        "codex_extra_args": args.codex_extra_args,
        "tasks_file": args.tasks_file,
        "system_prompt_file": args.system_prompt,
        "creation_profile": args.creation_profile,
        "pre_bmk_gate": args.pre_bmk_gate,
        "max_concurrent": args.max_concurrent,
        "timeout_minutes": args.timeout_minutes,
    }
    for key, value in override_fields.items():
        if value is not None:
            config[key] = value
    if args.no_system_prompt:
        config["include_system_prompt"] = False
    if args.codex_enable_search:
        config["codex_enable_search"] = True
    if args.output_dir is not None:
        config["output_dir"] = args.output_dir
    elif args.run_id:
        config["output_dir"] = str(Path(str(config.get("output_dir", "./outputs"))) / args.run_id)
    config["run_id"] = args.run_id
    return config


def normalize_creation_profile(value: str | None) -> str:
    profile = (value or "interface_tool").strip().lower().replace("-", "_")
    aliases = {
        "interface_tool": "interface_tool",
        "interfacetool": "interface_tool",
        "interface": "interface",
        "freeform": "freeform",
        "full_loop": "full_loop",
        "fullloop": "full_loop",
    }
    if profile not in aliases:
        raise ValueError(
            f"Unsupported creation_profile={value!r}. "
            "Supported values: freeform, interface, interface_tool, full_loop."
        )
    return aliases[profile]


def load_creation_profile_prompt(config: dict) -> tuple[str, str]:
    profile = normalize_creation_profile(str(config.get("creation_profile") or "interface_tool"))
    profile_dir = Path(str(config.get("creation_profile_dir") or "./prompts/creation/profiles"))
    profile_path = profile_dir / f"{profile}.md"
    if not profile_path.is_file():
        raise FileNotFoundError(f"creation profile prompt not found: {profile_path}")
    return profile, profile_path.read_text(encoding="utf-8").strip()


def resolve_config_models(config: dict) -> dict:
    aliases = config.get("model_aliases")
    if not isinstance(aliases, dict):
        aliases = {}
    codex_aliases = config.get("codex_model_aliases")
    if not isinstance(codex_aliases, dict):
        codex_aliases = {}

    raw_model_name = config.get("model_name")
    raw_eval_model_name = config.get("eval_model_name")
    if str(config.get("meta_harness") or "claude-code") == "codex":
        resolved_model_name = resolve_codex_model_alias(raw_model_name, codex_aliases)
    else:
        resolved_model_name = resolve_model_alias(raw_model_name, aliases)
    resolved_eval_model_name = resolve_model_alias(raw_eval_model_name, aliases)
    if raw_model_name:
        config["model_name_input"] = raw_model_name
        config["model_name"] = resolved_model_name
    if raw_eval_model_name:
        config["eval_model_name_input"] = raw_eval_model_name
        config["eval_model_name"] = resolved_eval_model_name
    return config


def print_model_aliases(config: dict) -> None:
    aliases = config.get("model_aliases") if isinstance(config.get("model_aliases"), dict) else {}
    codex_aliases = config.get("codex_model_aliases") if isinstance(config.get("codex_model_aliases"), dict) else {}
    print("[provider/openrouter aliases]")
    for key, value in sorted(merged_model_aliases(aliases).items()):
        if key in BUILTIN_MODEL_ALIASES or key in aliases:
            print(f"{key}: {value}")
    print("\n[codex aliases]")
    merged_codex = dict(BUILTIN_CODEX_MODEL_ALIASES)
    merged_codex.update({str(key).strip().lower().replace(" ", ""): str(value) for key, value in codex_aliases.items()})
    for key, value in sorted(merged_codex.items()):
        print(f"{key}: {value}")


def validate_generation_config(config: dict) -> None:
    meta_harness = str(config.get("meta_harness") or "claude-code")
    supported_meta_harnesses = {"claude-code", "codex"}
    if meta_harness not in supported_meta_harnesses:
        raise ValueError(
            f"Unsupported meta_harness={meta_harness!r}. "
            "Supported values: " + ", ".join(sorted(supported_meta_harnesses)) + "."
        )
    required_keys = ("base_url", "api_key", "model_name") if meta_harness == "claude-code" else ("model_name",)
    missing = [key for key in required_keys if not config.get(key)]
    if missing:
        raise ValueError(
            "Missing generation LLM config: "
            + ", ".join(missing)
            + ". Provide config.yaml or pass the corresponding CLI flags."
        )


def load_tasks(tasks_file: str) -> list[dict]:
    tasks = []
    with open(tasks_file) as f:
        for line in f:
            line = line.strip()
            if line:
                tasks.append(json.loads(line))
    return tasks


def compose_prompt(prompt: str, config: dict) -> str:
    if not config.get("include_system_prompt", True):
        return prompt
    system_prompt_file = config.get("system_prompt_file")
    if not system_prompt_file:
        return prompt
    system_path = Path(str(system_prompt_file))
    if not system_path.is_file():
        raise FileNotFoundError(f"system_prompt_file not found: {system_path}")
    system_prompt = system_path.read_text(encoding="utf-8").strip()
    creation_profile, profile_prompt = load_creation_profile_prompt(config)
    task_prompt = prompt.strip()
    return (
        f"{system_prompt}\n\n"
        "---\n\n"
        f"# Creation Profile: {creation_profile}\n\n"
        f"{profile_prompt}\n\n"
        "---\n\n"
        "# Task Prompt\n\n"
        f"{task_prompt}\n"
    )


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
        claude_md = ws / "CLAUDE.md"
        if not claude_md.exists():
            raise FileNotFoundError(f"CLAUDE.md not found in {task_dir}")
        claude_md.write_text(compose_prompt(claude_md.read_text(encoding="utf-8"), task["_config"]), encoding="utf-8")

    elif "prompt_file" in task:
        prompt_path = Path(task["prompt_file"])
        if not prompt_path.is_file():
            raise FileNotFoundError(f"prompt_file not found: {prompt_path}")
        (ws / "CLAUDE.md").write_text(
            compose_prompt(prompt_path.read_text(encoding="utf-8"), task["_config"]),
            encoding="utf-8",
        )

    elif "prompt" in task:
        (ws / "CLAUDE.md").write_text(compose_prompt(task["prompt"], task["_config"]), encoding="utf-8")

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


def run_claude_code_generation(task_id: str, workspace: str, config: dict, timeout: int) -> tuple[str, str, str]:
    container_name = f"harness-eval-{task_id}-{int(time.time())}"
    try:
        result = subprocess.run(
            [
                "docker", "run",
                "--name", container_name,
                "-e", f"BASE_URL={config['base_url']}",
                "-e", f"API_KEY={config['api_key']}",
                "-e", f"MODEL_NAME={config['model_name']}",
                "-e", f"CLAUDE_MODEL_NAME={config.get('claude_model_name', 'claude-sonnet-4-6')}",
                "-e", f"CLAUDE_NATIVE_ANTHROPIC={os.environ.get('CLAUDE_NATIVE_ANTHROPIC', '1' if 'anthropic' in str(config.get('base_url', '')).lower() else '')}",
                "-e", f"ANTHROPIC_BASE_URL={os.environ.get('ANTHROPIC_BASE_URL', config.get('base_url', ''))}",
                "-e", f"ANTHROPIC_AUTH_TOKEN={os.environ.get('ANTHROPIC_AUTH_TOKEN', config.get('api_key', ''))}",
                "-e", f"ANTHROPIC_API_KEY={os.environ.get('ANTHROPIC_API_KEY', os.environ.get('ANTHROPIC_AUTH_TOKEN', config.get('api_key', '')))}",
                "-e", f"ANTHROPIC_MODEL={os.environ.get('ANTHROPIC_MODEL', config.get('model_name', ''))}",
                "-e", f"CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING={os.environ.get('CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING', '')}",
                "-e", f"CLAUDE_CODE_THINKING={os.environ.get('CLAUDE_CODE_THINKING', '')}",
                "-e", f"CLAUDE_CODE_THINKING_EFFORT={os.environ.get('CLAUDE_CODE_THINKING_EFFORT', config.get('reasoning_effort') or '')}",
                "-e", f"META_HARNESS={config.get('meta_harness', 'claude-code')}",
                "-e", f"CLAUDE_REASONING_EFFORT={config.get('reasoning_effort') or ''}",
                "-e", f"OPENROUTER_VERBOSITY={config.get('reasoning_effort') or ''}",
                "-e", f"OPENROUTER_REASONING_ENABLED={'true' if config.get('reasoning_effort') else ''}",
                "-v", f"{workspace}:/workspace",
                "harness-eval",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        status = "success" if result.returncode == 0 else "failed"
        return status, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "stop", "-t", "5", container_name], capture_output=True)
        return "timeout", "", "Task timed out"
    except Exception as e:
        return "error", "", str(e)
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)


def codex_reasoning_effort(value: str | None) -> str | None:
    if not value:
        return None
    if value == "max":
        return "xhigh"
    return value


def run_codex_generation(task_id: str, workspace: str, config: dict, timeout: int) -> tuple[str, str, str]:
    codex_bin = str(config.get("codex_bin") or "codex")
    resolved_codex_bin = shutil.which(codex_bin) or codex_bin
    if not Path(resolved_codex_bin).exists() and shutil.which(resolved_codex_bin) is None:
        return "error", "", f"Codex binary not found: {codex_bin}. Set --codex-bin or CODEX_BIN."

    output_last_message = Path(workspace) / "codex_last_message.txt"
    prompt = (
        "Read CLAUDE.md in the current directory and complete the harness creation task. "
        "Write the requested harness files into this workspace. "
        "Do not stop at a plan; implement the runnable artifact described by the prompt."
    )
    command = [
        resolved_codex_bin,
        "exec",
        "-C",
        workspace,
        "-m",
        str(config["model_name"]),
        "-s",
        str(config.get("codex_sandbox") or "workspace-write"),
        "-a",
        "never",
        "--skip-git-repo-check",
        "--output-last-message",
        str(output_last_message),
    ]
    effort = codex_reasoning_effort(config.get("reasoning_effort"))
    if effort:
        command.extend(["-c", f'model_reasoning_effort="{effort}"'])
    if config.get("codex_enable_search"):
        command.append("--search")
    extra_args = config.get("codex_extra_args")
    if extra_args:
        if isinstance(extra_args, str):
            command.extend(shlex.split(extra_args))
        elif isinstance(extra_args, list):
            command.extend([str(item) for item in extra_args])
    command.append(prompt)

    env = os.environ.copy()
    for key in ("base_url", "api_key", "model_name"):
        if config.get(key):
            env_key = {
                "base_url": "OPENAI_BASE_URL",
                "api_key": "OPENAI_API_KEY",
                "model_name": "MODEL_NAME",
            }[key]
            env[env_key] = str(config[key])
    try:
        result = subprocess.run(
            command,
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        (Path(workspace) / "codex_command.json").write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "command": [part if part != str(config.get("api_key")) else "<redacted>" for part in command],
                    "model_name": config.get("model_name"),
                    "reasoning_effort": config.get("reasoning_effort"),
                    "codex_sandbox": config.get("codex_sandbox"),
                    "codex_enable_search": bool(config.get("codex_enable_search")),
                    "returncode": result.returncode,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        status = "success" if result.returncode == 0 else "failed"
        return status, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return "timeout", "", "Task timed out"
    except Exception as e:
        return "error", "", str(e)


def run_generation(task_id: str, workspace: str, config: dict, timeout: int) -> tuple[str, str, str]:
    meta_harness = str(config.get("meta_harness") or "claude-code")
    if meta_harness == "claude-code":
        return run_claude_code_generation(task_id, workspace, config, timeout)
    if meta_harness == "codex":
        return run_codex_generation(task_id, workspace, config, timeout)
    return "error", "", f"Unsupported meta_harness={meta_harness!r}"


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

    timeout = config.get("timeout_minutes", 30) * 60
    status, stdout, stderr = run_generation(task_id, workspace, config, timeout)

    SKIP_DIRS = {".git", "venv", ".venv", "node_modules", "__pycache__"}
    for item in Path(workspace).iterdir():
        dest = task_output_dir / item.name
        if item.is_dir():
            if item.name in SKIP_DIRS:
                continue
            try:
                shutil.copytree(item, dest, dirs_exist_ok=True)
            except shutil.Error:
                shutil.copytree(item, dest, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns("python*", "python3*"))
        else:
            shutil.copy2(item, dest)

    meta = {
        "task_id": task_id,
        "status": status,
        "run_id": config.get("run_id"),
        "meta_harness": config.get("meta_harness", "claude-code"),
        "creation_profile": config.get("creation_profile", "interface_tool"),
        "pre_bmk_gate": config.get("pre_bmk_gate", "soft"),
        "generation_model_input": config.get("model_name_input"),
        "generation_model": config.get("model_name"),
        "eval_model_input": config.get("eval_model_name_input"),
        "eval_model": config.get("eval_model_name"),
        "claude_model_name": config.get("claude_model_name", "claude-sonnet-4-6"),
        "codex_bin": config.get("codex_bin") if config.get("meta_harness") == "codex" else None,
        "codex_sandbox": config.get("codex_sandbox") if config.get("meta_harness") == "codex" else None,
        "codex_enable_search": bool(config.get("codex_enable_search")) if config.get("meta_harness") == "codex" else None,
        "reasoning_effort": config.get("reasoning_effort"),
        "system_prompt_file": config.get("system_prompt_file") if config.get("include_system_prompt", True) else None,
        "task_prompt_file": task.get("prompt_file"),
        "stdout": stdout[-5000:] if stdout else "",
        "stderr": stderr[-5000:] if stderr else "",
    }

    metrics_file = task_output_dir / "metrics.json"
    if metrics_file.exists():
        try:
            metrics = json.loads(metrics_file.read_text())
            meta["metrics"] = {
                "total_requests": metrics.get("total_requests", 0),
                "total_input_tokens": metrics.get("total_input_tokens", 0),
                "total_output_tokens": metrics.get("total_output_tokens", 0),
                "total_cache_read_tokens": metrics.get("total_cache_read_tokens", 0),
                "total_cache_creation_tokens": metrics.get("total_cache_creation_tokens", 0),
                "total_tokens": metrics.get("total_input_tokens", 0) + metrics.get("total_output_tokens", 0),
                "effective_requests": metrics.get("effective_requests", 0),
                "effective_input_tokens": metrics.get("effective_input_tokens", 0),
                "effective_output_tokens": metrics.get("effective_output_tokens", 0),
                "retry_requests": metrics.get("retry_requests", 0),
            }
        except (json.JSONDecodeError, KeyError):
            pass

    (task_output_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    shutil.rmtree(workspace, ignore_errors=True)

    print(f"[{task_id}] {status}")
    return meta


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate harness artifacts with Claude Code, optionally followed by downstream BMK eval."
    )
    parser.add_argument("config", nargs="?", default="config.yaml")
    parser.add_argument("--run-id", default=None, help="Generation run id. Output goes to output_dir/run-id.")
    parser.add_argument("--output-dir", default=None, help="Exact generation output directory.")
    parser.add_argument(
        "--meta-harness",
        default=None,
        choices=["claude-code", "codex"],
        help="Meta harness used to generate a harness.",
    )
    parser.add_argument("--codex-bin", default=None, help="Codex CLI binary used when --meta-harness codex.")
    parser.add_argument(
        "--codex-sandbox",
        default=None,
        choices=["read-only", "workspace-write", "danger-full-access"],
        help="Codex CLI sandbox mode for --meta-harness codex. Default: workspace-write.",
    )
    parser.add_argument(
        "--codex-enable-search",
        action="store_true",
        help="Pass --search to Codex CLI when --meta-harness codex.",
    )
    parser.add_argument(
        "--codex-extra-args",
        default=None,
        help="Extra raw args appended to codex exec, for advanced local Codex config overrides.",
    )
    parser.add_argument("--base-url", default=None, help="OpenAI-compatible chat completions URL for generation.")
    parser.add_argument("--api-key", default=None, help="API key for generation LLM.")
    parser.add_argument("--model-name", default=None, help="Backend LLM model used by the meta harness.")
    parser.add_argument(
        "--claude-model-name",
        default=None,
        help="Claude-family alias passed to Claude Code CLI; router still sends to --model-name.",
    )
    parser.add_argument(
        "--reasoning-effort",
        default=None,
        choices=["low", "medium", "high", "xhigh", "max"],
        help="Reasoning/effort level for Claude Code and OpenRouter verbosity. Use max for strongest Opus 4.7 runs.",
    )
    parser.add_argument("--tasks-file", default=None, help="JSONL task file for harness creation.")
    parser.add_argument("--system-prompt", default=None, help="System prompt prepended to each task prompt.")
    parser.add_argument(
        "--creation-profile",
        default=None,
        choices=["freeform", "interface", "interface_tool", "interface-tool", "full_loop", "full-loop"],
        help="Harness creation profile. Main experiment default: interface_tool.",
    )
    parser.add_argument(
        "--pre-bmk-gate",
        default=None,
        choices=["off", "soft", "hard"],
        help="Pre-BMK validation gate used by --eval-after. soft records failures but still runs BMK; hard skips failed harnesses.",
    )
    parser.add_argument("--no-system-prompt", action="store_true", help="Do not prepend system prompt.")
    parser.add_argument("--max-concurrent", type=int, default=None)
    parser.add_argument("--timeout-minutes", type=int, default=None)
    parser.add_argument("--list-model-aliases", action="store_true", help="Print built-in and config-defined model aliases and exit.")
    parser.add_argument("--list-tasks", action="store_true", help="List available creation tasks and exit.")
    parser.add_argument(
        "--task-id",
        default=None,
        help="Comma-separated creation task ids to run, for example code-agent-harness or writing-harness.",
    )
    parser.add_argument(
        "--eval-after",
        action="store_true",
        help="Run run_creation_eval.py on the generated output directory after creation finishes.",
    )
    parser.add_argument("--eval-bench", default="all", help="Comma-separated BMK ids for post-creation eval.")
    parser.add_argument("--eval-domain", default=None, help="Comma-separated domains for post-creation eval.")
    parser.add_argument("--eval-run-id", default=None, help="Run id for post-creation eval.")
    parser.add_argument("--eval-matrix", default="eval_matrix.yaml")
    parser.add_argument("--eval-output-root", default="eval_results")
    parser.add_argument("--eval-base-url", default=None, help="OpenAI-compatible base URL or chat completions URL for eval-time harness LLM. Defaults to generation --base-url.")
    parser.add_argument("--eval-api-key", default=None, help="API key for eval-time harness LLM. Defaults to generation --api-key.")
    parser.add_argument("--eval-model-name", default=None, help="Model used by the generated harness during downstream eval. Defaults to generation --model-name.")
    parser.add_argument(
        "--eval-reasoning-effort",
        default=None,
        choices=["low", "medium", "high", "xhigh", "max"],
        help="Reasoning/verbosity level for eval-time harness LLM. Defaults to --reasoning-effort.",
    )
    parser.add_argument(
        "--no-eval-provider-proxy",
        action="store_true",
        help="Do not start a local eval provider proxy; pass eval LLM config directly to generated harnesses.",
    )
    parser.add_argument("--eval-provider-proxy-port", type=int, default=3458)
    parser.add_argument(
        "--harness-evolve-root",
        default="/Users/bytedance/Downloads/harness evolve project",
    )
    parser.add_argument("--python-bin", default=sys.executable)
    parser.add_argument("--eval-timeout-seconds", default="3600")
    parser.add_argument(
        "--eval-dry-run",
        action="store_true",
        help="Validate and dependency-check only during post-creation eval.",
    )
    return parser.parse_args()


def run_downstream_eval(output_dir: Path, args: argparse.Namespace, config: dict) -> int:
    eval_model_name = config.get("eval_model_name") or config.get("model_name")
    eval_base_url = config.get("eval_base_url") or config.get("base_url")
    eval_api_key = config.get("eval_api_key") or config.get("api_key")
    eval_reasoning_effort = config.get("eval_reasoning_effort") or config.get("reasoning_effort")
    eval_run_id = args.eval_run_id or ((config.get("run_id") or output_dir.name) + "-eval")
    command = [
        args.python_bin,
        "run_creation_eval.py",
        "--generation-output",
        str(output_dir),
        "--matrix",
        args.eval_matrix,
        "--bench",
        args.eval_bench,
        "--eval-output-root",
        args.eval_output_root,
        "--harness-evolve-root",
        args.harness_evolve_root,
        "--python-bin",
        args.python_bin,
        "--timeout-seconds",
        str(args.eval_timeout_seconds),
        "--eval-model-name",
        str(eval_model_name),
        "--eval-base-url",
        str(eval_base_url),
    ]
    child_env = os.environ.copy()
    child_env["EVAL_API_KEY"] = str(eval_api_key or "")
    if eval_reasoning_effort:
        command.extend(["--eval-reasoning-effort", str(eval_reasoning_effort)])
    if args.no_eval_provider_proxy:
        command.append("--no-eval-provider-proxy")
    command.extend(["--eval-provider-proxy-port", str(args.eval_provider_proxy_port)])
    if args.eval_domain:
        command.extend(["--domain", args.eval_domain])
    command.extend(["--run-id", eval_run_id])
    if args.eval_dry_run:
        command.append("--dry-run")
    command.extend(["--pre-bmk-gate", str(config.get("pre_bmk_gate") or "soft")])

    print("\nRunning downstream BMK eval:")
    print(" ".join(command))
    return subprocess.run(command, env=child_env).returncode


def main():
    args = parse_args()
    config = resolve_config_models(apply_cli_overrides(load_config(args.config), args))
    config["creation_profile"] = normalize_creation_profile(str(config.get("creation_profile") or "interface_tool"))
    config["pre_bmk_gate"] = str(config.get("pre_bmk_gate") or "soft")

    if args.list_model_aliases:
        print_model_aliases(config)
        return

    tasks = load_tasks(config.get("tasks_file", "tasks.jsonl"))
    for task in tasks:
        task["_config"] = config
    if args.list_tasks:
        for task in tasks:
            print(task.get("id"))
        return
    if args.task_id:
        selected_task_ids = {item.strip() for item in args.task_id.split(",") if item.strip()}
        tasks = [task for task in tasks if task.get("id") in selected_task_ids]
    if not tasks:
        print("No tasks found.")
        return
    validate_generation_config(config)

    output_dir = Path(config.get("output_dir", "./outputs"))
    output_dir.mkdir(parents=True, exist_ok=True)

    if str(config.get("meta_harness") or "claude-code") == "claude-code":
        build_docker_image()

    max_concurrent = config.get("max_concurrent", 4)
    print(f"Running {len(tasks)} task(s) with max {max_concurrent} concurrent worker(s)...")

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

    if args.eval_after:
        eval_code = run_downstream_eval(output_dir, args, config)
        if eval_code != 0:
            raise SystemExit(eval_code)


if __name__ == "__main__":
    main()
