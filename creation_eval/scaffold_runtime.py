from __future__ import annotations

import json
import os
from pathlib import Path


PROGRAM_CANDIDATE_NAMES = (
    "generated_program.py",
    "harness_program.py",
    "program.py",
)

MANIFEST_CANDIDATE_NAMES = (
    "scaffold_manifest.json",
    "harness_scaffold_manifest.json",
)

SCAFFOLD_RESOURCE_PROFILES = {
    "claude_code_scaffold",
    "claude_code_scaffold_native",
}

SCAFFOLD_NATIVE_PROFILES = {
    "claude_code_scaffold_native",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def vendor_root() -> Path:
    return repo_root() / "vendor"


def vendor_scaffold_dir() -> Path:
    return vendor_root() / "harness_scaffold"


def scaffold_source_available() -> bool:
    return (vendor_scaffold_dir() / "adapters" / "cli.py").is_file()


def is_scaffold_resource_profile(profile: str | None) -> bool:
    normalized = (profile or "").strip().lower().replace("-", "_")
    return normalized in SCAFFOLD_RESOURCE_PROFILES


def is_scaffold_native_profile(profile: str | None) -> bool:
    normalized = (profile or "").strip().lower().replace("-", "_")
    return normalized in SCAFFOLD_NATIVE_PROFILES


def has_scaffold_manifest(root: Path) -> bool:
    root = Path(root)
    return any((root / name).is_file() for name in MANIFEST_CANDIDATE_NAMES)


def should_prefer_scaffold_runtime(root: Path, profile: str | None = None) -> bool:
    if is_scaffold_native_profile(profile):
        return True
    root = Path(root)
    if has_scaffold_manifest(root):
        return True
    try:
        meta = json.loads((root / "meta.json").read_text(encoding="utf-8"))
    except Exception:
        meta = {}
    return is_scaffold_native_profile(str(meta.get("creation_profile") or ""))


def scaffold_pythonpath(root: Path, program_path: Path | None = None) -> list[str]:
    paths = [str(root), str(vendor_root())]
    harness_dir = root / "harness"
    if harness_dir.is_dir():
        paths.append(str(harness_dir))
    if program_path is not None:
        paths.append(str(program_path.parent))
    return paths


def apply_scaffold_pythonpath(env: dict[str, str], root: Path, program_path: Path | None = None) -> None:
    env["PYTHONPATH"] = os.pathsep.join(
        scaffold_pythonpath(root, program_path) + [env.get("PYTHONPATH", "")]
    )


def _program_from_manifest(root: Path) -> Path | None:
    for manifest_name in MANIFEST_CANDIDATE_NAMES:
        manifest = root / manifest_name
        if not manifest.is_file():
            continue
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            continue
        for key in ("program", "program_path", "generated_program"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                candidate = (root / value).resolve()
                try:
                    candidate.relative_to(root.resolve())
                except ValueError:
                    continue
                if candidate.is_file():
                    return candidate
    return None


def find_scaffold_program(root: Path) -> Path | None:
    root = Path(root)
    manifest_program = _program_from_manifest(root)
    if manifest_program is not None:
        return manifest_program

    search_roots = [root, root / "harness", root / "scaffold"]
    for base in search_roots:
        if not base.exists():
            continue
        for name in PROGRAM_CANDIDATE_NAMES:
            candidate = base / name
            if candidate.is_file():
                return candidate.resolve()

    for path in root.rglob("*.py"):
        if "harness_scaffold" in path.parts:
            continue
        if "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "PROGRAM =" in text or "def get_program(" in text:
            return path.resolve()
    return None


def is_scaffold_style_artifact(root: Path) -> bool:
    return find_scaffold_program(root) is not None
