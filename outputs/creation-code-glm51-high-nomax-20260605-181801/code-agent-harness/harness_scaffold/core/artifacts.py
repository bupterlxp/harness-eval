"""Artifact store. All artifacts live under ``out_dir``; sizes are enforced.

Generated harnesses use this to persist anything that is NOT the single stdout
JSON line: reports, patches, screenshots, evidence, metrics, etc. Every put
returns a :class:`pathlib.Path`. ``write_manifest`` emits ``artifacts.json``.

NO third-party imports.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Optional

from .errors import ArtifactError
from .serialization import safe_json_dumps, write_json_file

# Standard, well-known artifact filenames (the BMK out-dir contract).
MANIFEST_NAME = "artifacts.json"


class ArtifactStore:
    def __init__(self, out_dir: Path, *, max_artifact_bytes: int = 10_000_000) -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.max_artifact_bytes = int(max_artifact_bytes)
        # name -> {path, size_bytes, kind}
        self._manifest: dict[str, dict[str, Any]] = {}

    # --- internal helpers ------------------------------------------------ #

    def _target(self, name: str) -> Path:
        """Resolve ``name`` to a path strictly under out_dir.

        ``name`` may contain subdirectories (e.g. ``screenshots/p1.png``) but
        may not escape out_dir.
        """
        if not name or name in (".", ".."):
            raise ArtifactError(f"invalid artifact name: {name!r}", stage="artifact")
        candidate = (self.out_dir / name).resolve()
        out_root = self.out_dir.resolve()
        try:
            candidate.relative_to(out_root)
        except ValueError as exc:
            raise ArtifactError(
                f"artifact path escapes out_dir: {name!r}",
                stage="artifact",
                details={"name": name, "resolved": str(candidate)},
            ) from exc
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate

    def _check_size(self, n_bytes: int, name: str) -> None:
        if self.max_artifact_bytes > 0 and n_bytes > self.max_artifact_bytes:
            raise ArtifactError(
                f"artifact {name!r} exceeds max size ({n_bytes} > {self.max_artifact_bytes})",
                stage="artifact",
                details={"name": name, "size_bytes": n_bytes, "limit": self.max_artifact_bytes},
            )

    # --- puts ------------------------------------------------------------ #

    def put_text(self, name: str, content: str, *, kind: str = "text") -> Path:
        raw = content.encode("utf-8")
        self._check_size(len(raw), name)
        path = self._target(name)
        path.write_bytes(raw)
        return self.register(name, path, kind=kind, size_bytes=len(raw))

    def put_bytes(self, name: str, content: bytes, *, kind: str = "binary") -> Path:
        self._check_size(len(content), name)
        path = self._target(name)
        path.write_bytes(content)
        return self.register(name, path, kind=kind, size_bytes=len(content))

    def put_json(self, name: str, obj: Any, *, kind: str = "json", indent: int = 2) -> Path:
        text = safe_json_dumps(obj, indent=indent)
        return self.put_text(name, text, kind=kind)

    def put_file(self, name: str, src: Path, *, kind: str = "file") -> Path:
        src = Path(src)
        if not src.exists():
            raise ArtifactError(
                f"source file does not exist: {src}",
                stage="artifact",
                details={"name": name, "src": str(src)},
            )
        size = src.stat().st_size
        self._check_size(size, name)
        path = self._target(name)
        shutil.copy2(src, path)
        return self.register(name, path, kind=kind, size_bytes=size)

    # --- registration / manifest ---------------------------------------- #

    def register(
        self,
        name: str,
        path: Path,
        *,
        kind: str = "file",
        size_bytes: Optional[int] = None,
    ) -> Path:
        """Record an already-written artifact in the manifest. Returns Path."""
        path = Path(path)
        if size_bytes is None:
            try:
                size_bytes = path.stat().st_size
            except OSError:
                size_bytes = 0
        self._manifest[name] = {
            "path": str(path),
            "size_bytes": int(size_bytes),
            "kind": kind,
        }
        return path

    def get(self, name: str) -> Optional[Path]:
        entry = self._manifest.get(name)
        return Path(entry["path"]) if entry else None

    def paths(self) -> dict[str, Path]:
        return {k: Path(v["path"]) for k, v in self._manifest.items()}

    def manifest(self) -> dict[str, Any]:
        return {
            "out_dir": str(self.out_dir),
            "count": len(self._manifest),
            "artifacts": {k: dict(v) for k, v in self._manifest.items()},
        }

    def write_manifest(self) -> Path:
        return write_json_file(self.out_dir / MANIFEST_NAME, self.manifest())

    def to_dict(self) -> dict[str, Any]:
        return self.manifest()
