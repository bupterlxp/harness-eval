from __future__ import annotations

import os
import re
from pathlib import Path

from .schema import HarnessArtifact, ValidationResult
from .scaffold_runtime import (
    apply_scaffold_pythonpath,
    find_scaffold_program,
    is_scaffold_native_profile,
    should_prefer_scaffold_runtime,
)
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
        timeout=min(max(timeout, 60), 180),
    )
    if install.returncode != 0:
            result.errors.append(f"requirements_install_failed: {install.stderr.strip() or install.stdout.strip()}")


def _help_probe_ok(probe) -> bool:
    if probe.returncode == 0:
        return True
    output = f"{probe.stdout}\n{probe.stderr}".lower()
    # Some generated CLIs catch argparse's SystemExit(0) incorrectly and
    # return 2 after printing valid help. Treat that as a runnable CLI, while
    # keeping real argparse errors invalid.
    return probe.returncode == 2 and "usage:" in output and "options:" in output and "error:" not in output


def _validate_scaffold_artifact(
    artifact: HarnessArtifact,
    result: ValidationResult,
    python_bin: str,
    timeout: int,
    program_path: Path,
) -> ValidationResult:
    syntax = run_command([python_bin, "-m", "py_compile", str(program_path)], timeout=timeout)
    result.syntax_ok = syntax.returncode == 0
    if not result.syntax_ok:
        result.errors.append(f"syntax_check_failed: {syntax.stderr.strip() or syntax.stdout.strip()}")

    env = os.environ.copy()
    shim_dir = Path(__file__).resolve().parent / "shims"
    apply_scaffold_pythonpath(env, artifact.path, program_path)
    env["PYTHONPATH"] = os.pathsep.join([str(shim_dir), env.get("PYTHONPATH", "")])
    import_code = (
        "from pathlib import Path; "
        "from harness_scaffold.adapters.generated_harness_adapter import load_program; "
        f"load_program(Path({str(program_path)!r})); "
        "print('ok')"
    )
    imported = run_command([python_bin, "-c", import_code], cwd=artifact.path, env=env, timeout=timeout)
    result.import_ok = imported.returncode == 0
    if not result.import_ok:
        missing = _missing_module(imported.stderr)
        if missing:
            result.missing_dependencies.append(missing)
        result.errors.append(f"scaffold_import_check_failed: {imported.stderr.strip() or imported.stdout.strip()}")

    probe = run_command(
        [python_bin, "-m", "harness_scaffold.adapters.cli", "--help"],
        cwd=artifact.path,
        env=env,
        timeout=30,
    )
    result.cli_probe_ok = probe.returncode == 0 and "harness_scaffold.adapters.cli" in probe.stdout
    if not result.cli_probe_ok:
        result.errors.append(f"scaffold_cli_probe_failed: {probe.stderr.strip() or probe.stdout.strip()}")

    result.meta["scaffold_program"] = str(program_path)
    if result.generation_status != "success":
        result.adapter_status = "invalid_generation_status"
    elif result.syntax_ok and result.import_ok and result.cli_probe_ok:
        result.adapter_status = "ready"
    else:
        result.adapter_status = "invalid"
    return result


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
        creation_attempts=meta.get("creation_attempts"),
        repair_rounds=meta.get("repair_rounds"),
        gate_pass_before_repair=meta.get("gate_pass_before_repair"),
        gate_pass_after_repair=meta.get("gate_pass_after_repair"),
        repair_failure_reasons=meta.get("repair_failure_reasons") if isinstance(meta.get("repair_failure_reasons"), list) else [],
        repair_tokens=meta.get("repair_tokens"),
        selected_attempt_path=str(meta.get("selected_attempt_path") or ""),
        harness_run_interactions=interactions,
        meta=meta,
        metrics=metrics,
        raw_result_path=str((artifact.path / "meta.json").resolve()) if (artifact.path / "meta.json").exists() else "",
    )

    harness_dir = artifact.path / "harness"
    scaffold_program = find_scaffold_program(artifact.path)
    creation_profile = str(meta.get("creation_profile") or "")
    if is_scaffold_native_profile(creation_profile) and scaffold_program is None:
        result.errors.append(
            "scaffold_native_required: expected scaffold_manifest.json plus generated_program.py "
            "or another PROGRAM/get_program scaffold program"
        )
        result.syntax_ok = False
        result.import_ok = False
        result.cli_probe_ok = False
        result.adapter_status = "invalid"
        result.meta["scaffold_native_required"] = True
        return result

    if scaffold_program is not None and (
        not harness_dir.is_dir() or should_prefer_scaffold_runtime(artifact.path, creation_profile)
    ):
        result.meta["scaffold_native_required"] = is_scaffold_native_profile(creation_profile)
        return _validate_scaffold_artifact(artifact, result, python_bin, timeout, scaffold_program)

    if not harness_dir.is_dir():
        result.errors.append("missing harness/ directory")
        result.adapter_status = "invalid"
        return result

    syntax = run_command([python_bin, "-m", "compileall", "-q", str(harness_dir)], timeout=timeout)
    result.syntax_ok = syntax.returncode == 0
    if not result.syntax_ok:
        result.errors.append(f"syntax_check_failed: {syntax.stderr.strip() or syntax.stdout.strip()}")

    env = os.environ.copy()
    shim_dir = Path(__file__).resolve().parent / "shims"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(artifact.path), str(shim_dir), env.get("PYTHONPATH", "")]
    )
    import_code = "import harness; print('ok')"
    imported = run_command([python_bin, "-c", import_code], cwd=artifact.path, env=env, timeout=timeout)
    result.import_ok = imported.returncode == 0
    if not result.import_ok:
        missing = _missing_module(imported.stderr)
        if missing:
            result.missing_dependencies.append(missing)
            _install_requirements(artifact.path, python_bin, result, timeout)
            imported = run_command([python_bin, "-c", import_code], cwd=artifact.path, env=env, timeout=timeout)
            result.import_ok = imported.returncode == 0
            if not result.import_ok:
                result.errors.append(f"import_check_failed: {imported.stderr.strip() or imported.stdout.strip()}")
        else:
            result.errors.append(f"import_check_failed: {imported.stderr.strip() or imported.stdout.strip()}")

    cli_commands = [
        [python_bin, "-m", "harness", "--help"],
        [python_bin, "-m", "harness.cli", "--help"],
    ]
    for command in cli_commands:
        probe = run_command(command, cwd=artifact.path, env=env, timeout=30)
        if _help_probe_ok(probe):
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
