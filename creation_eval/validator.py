from __future__ import annotations

import os
import re
from pathlib import Path

from .schema import HarnessArtifact, ValidationResult
from .utils import read_json, run_command


DOMAIN_BY_TASK_ID = {
    "code-agent-harness": "code",
    "data-analysis-harness": "data_analysis",
    "writing-harness": "writing",
    "research-agent-harness": "research",
    "browser-agent-harness": "browser",
}


def infer_domain(task_id: str, artifact_path: Path) -> str:
    if task_id in DOMAIN_BY_TASK_ID:
        return DOMAIN_BY_TASK_ID[task_id]
    lowered = f"{task_id} {artifact_path.name}".lower()
    if "code" in lowered:
        return "code"
    if "data" in lowered or "analysis" in lowered or "notebook" in lowered:
        return "data_analysis"
    if "writing" in lowered or "writer" in lowered:
        return "writing"
    if "research" in lowered or "deep" in lowered:
        return "research"
    if "browser" in lowered or "employee" in lowered:
        return "browser"
    return "unknown"


def infer_generation_model(generation_output: Path, artifact_path: Path, override: str | None = None) -> str:
    if override:
        return override
    if generation_output.is_dir() and artifact_path.parent == generation_output:
        return generation_output.name
    if artifact_path.parent.name:
        return artifact_path.parent.name
    return "unknown"


def discover_harness_artifacts(generation_output: Path, generation_model: str | None = None) -> list[HarnessArtifact]:
    generation_output = generation_output.resolve()
    if (generation_output / "harness").is_dir() or (generation_output / "meta.json").is_file():
        task_id = read_json(generation_output / "meta.json").get("task_id") or generation_output.name
        return [
            HarnessArtifact(
                path=generation_output,
                task_id=str(task_id),
                domain=infer_domain(str(task_id), generation_output),
                generation_model=infer_generation_model(generation_output.parent, generation_output, generation_model),
            )
        ]

    artifacts: list[HarnessArtifact] = []
    for child in sorted(p for p in generation_output.iterdir() if p.is_dir()):
        if not (child / "harness").is_dir() and not (child / "meta.json").is_file():
            continue
        task_id = read_json(child / "meta.json").get("task_id") or child.name
        artifacts.append(
            HarnessArtifact(
                path=child,
                task_id=str(task_id),
                domain=infer_domain(str(task_id), child),
                generation_model=infer_generation_model(generation_output, child, generation_model),
            )
        )
    return artifacts


def _missing_module(stderr: str) -> str | None:
    patterns = [
        r"ModuleNotFoundError: No module named '([^']+)'",
        r"ModuleNotFoundError: No module named \"([^\"]+)\"",
        r"ImportError: No module named ([^\s]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, stderr)
        if match:
            return f"python module: {match.group(1)}"
    return None


def _install_requirements(artifact_path: Path, python_bin: str, result: ValidationResult, timeout: int) -> None:
    requirements = artifact_path / "requirements.txt"
    if not requirements.is_file():
        return
    install = run_command(
        [
            python_bin,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-q",
            "-r",
            str(requirements),
        ],
        cwd=artifact_path,
        timeout=max(timeout, 300),
    )
    if install.returncode != 0:
        result.errors.append(f"requirements_install_failed: {install.stderr.strip() or install.stdout.strip()}")


def validate_artifact(artifact: HarnessArtifact, python_bin: str, timeout: int = 60) -> ValidationResult:
    meta = read_json(artifact.path / "meta.json")
    metrics = read_json(artifact.path / "metrics.json")
    generation_status = str(meta.get("status") or "missing_meta")
    generation_tokens = (
        meta.get("metrics", {}).get("total_tokens")
        or metrics.get("total_tokens")
        or (metrics.get("total_input_tokens", 0) + metrics.get("total_output_tokens", 0) or None)
    )
    interactions = (
        meta.get("metrics", {}).get("effective_requests")
        or meta.get("metrics", {}).get("total_requests")
        or metrics.get("effective_requests")
        or metrics.get("total_requests")
    )

    result = ValidationResult(
        generation_status=generation_status,
        generation_tokens=generation_tokens,
        harness_run_interactions=interactions,
        meta=meta,
        metrics=metrics,
        raw_result_path=str((artifact.path / "meta.json").resolve()) if (artifact.path / "meta.json").exists() else "",
    )

    harness_dir = artifact.path / "harness"
    if not harness_dir.is_dir():
        result.errors.append("missing harness/ directory")
        result.adapter_status = "invalid"
        return result

    syntax = run_command([python_bin, "-m", "compileall", "-q", str(harness_dir)], timeout=timeout)
    result.syntax_ok = syntax.returncode == 0
    if not result.syntax_ok:
        result.errors.append(f"syntax_check_failed: {syntax.stderr.strip() or syntax.stdout.strip()}")

    _install_requirements(artifact.path, python_bin, result, timeout)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(artifact.path)
    import_code = "import harness; print('ok')"
    imported = run_command([python_bin, "-c", import_code], cwd=artifact.path, env=env, timeout=timeout)
    result.import_ok = imported.returncode == 0
    if not result.import_ok:
        missing = _missing_module(imported.stderr)
        if missing:
            result.missing_dependencies.append(missing)
        result.errors.append(f"import_check_failed: {imported.stderr.strip() or imported.stdout.strip()}")

    cli_commands = [
        [python_bin, "-m", "harness", "--help"],
        [python_bin, "-m", "harness.cli", "--help"],
    ]
    for command in cli_commands:
        probe = run_command(command, cwd=artifact.path, env=env, timeout=30)
        if probe.returncode == 0:
            result.cli_probe_ok = True
            break
        missing = _missing_module(probe.stderr)
        if missing and missing not in result.missing_dependencies:
            result.missing_dependencies.append(missing)
    if not result.cli_probe_ok:
        result.errors.append("cli_probe_failed: python -m harness --help and python -m harness.cli --help both failed")

    if result.generation_status != "success":
        result.adapter_status = "invalid_generation_status"
    elif result.syntax_ok and result.import_ok and result.cli_probe_ok:
        result.adapter_status = "ready"
    else:
        result.adapter_status = "invalid"
    return result
