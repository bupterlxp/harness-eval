"""Permission / sandbox policy.

Confines filesystem writes to ``workdir`` + ``out_dir`` by default, gates
network and shell, and denylists obviously destructive shell commands. All
violations raise :class:`PermissionDenied` with structured details.

Extraction note: distilled from Claude Code's permission system
(``types/permissions.ts`` + per-tool permission checks) into a single
deterministic, dependency-free policy object suitable for a benchmark sandbox.

NO third-party imports.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

from .errors import PermissionDenied

# Regexes for clearly destructive / exfiltration-prone shell command shapes.
# These are coarse, deny-by-pattern guards (defense in depth, not a full parser).
_DENY_SHELL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("rm_rf_root", re.compile(r"\brm\s+(-[a-zA-Z]*\s+)*(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\b.*\s/(\s|$)")),
    ("rm_rf_root2", re.compile(r"\brm\s+-rf\s+/\s*$")),
    ("rm_rf_slashstar", re.compile(r"\brm\s+-rf\s+/\*")),
    ("rm_rf_home", re.compile(r"\brm\s+-rf\s+~(/|\s|$)")),
    ("mkfs", re.compile(r"\bmkfs(\.\w+)?\b")),
    ("dd_to_dev", re.compile(r"\bdd\b.*\bof=/dev/")),
    ("shutdown", re.compile(r"\b(shutdown|reboot|halt|poweroff|init\s+0|init\s+6)\b")),
    ("forkbomb", re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:")),
    ("curl_pipe_sh", re.compile(r"\b(curl|wget)\b.*\|\s*(sudo\s+)?(ba)?sh\b")),
    ("chmod_777_root", re.compile(r"\bchmod\s+-R?\s*777\s+/(\s|$)")),
    ("overwrite_devsda", re.compile(r">\s*/dev/(sd|nvme|hd)\w*")),
]

# Commands that imply network access when network is disabled.
_NETWORK_CMD_RE = re.compile(r"\b(curl|wget|nc|ncat|ssh|scp|sftp|ftp|telnet|rsync)\b")

# Commands that imply package installation (often hang the experiment).
_INSTALL_CMD_RE = re.compile(
    r"\b(pip3?\s+install|pip3?\s+download|npm\s+(install|i|ci)|yarn\s+add|"
    r"apt(-get)?\s+install|conda\s+install|poetry\s+add|brew\s+install)\b"
)


class PermissionPolicy:
    def __init__(
        self,
        workdir: Path,
        out_dir: Path,
        *,
        allow_network: bool = False,
        allow_shell: bool = True,
        allow_destructive_fs: bool = False,
        allow_install: bool = False,
        denied_commands: Optional[Iterable[str]] = None,
        extra_read_roots: Optional[Iterable[Path]] = None,
        extra_write_roots: Optional[Iterable[Path]] = None,
    ) -> None:
        self.workdir = _resolve(workdir)
        self.out_dir = _resolve(out_dir)
        self.allow_network = bool(allow_network)
        self.allow_shell = bool(allow_shell)
        self.allow_destructive_fs = bool(allow_destructive_fs)
        self.allow_install = bool(allow_install)
        self.denied_commands = [c.strip() for c in (denied_commands or []) if c.strip()]
        self.extra_read_roots = [_resolve(p) for p in (extra_read_roots or [])]
        self.extra_write_roots = [_resolve(p) for p in (extra_write_roots or [])]

    # --- filesystem ------------------------------------------------------ #

    def _write_roots(self) -> list[Path]:
        return [self.workdir, self.out_dir, *self.extra_write_roots]

    def _read_roots(self) -> list[Path]:
        # Reads are allowed from write roots + explicit extra read roots.
        return [self.workdir, self.out_dir, *self.extra_write_roots, *self.extra_read_roots]

    def check_path_read(self, path: Path) -> Path:
        """Validate read access; returns the resolved path or raises."""
        resolved = _resolve(path)
        if self.allow_destructive_fs:
            return resolved
        if _within_any(resolved, self._read_roots()):
            return resolved
        raise PermissionDenied(
            f"read outside permitted roots: {resolved}",
            stage="permission",
            details={
                "path": str(resolved),
                "operation": "read",
                "allowed_roots": [str(p) for p in self._read_roots()],
            },
        )

    def check_path_write(self, path: Path) -> Path:
        """Validate write access; returns the resolved path or raises.

        Default: writes confined to workdir + out_dir (+ extra write roots).
        ``allow_destructive_fs`` lifts the confinement.
        """
        resolved = _resolve(path)
        if self.allow_destructive_fs:
            return resolved
        if _within_any(resolved, self._write_roots()):
            return resolved
        raise PermissionDenied(
            f"write outside permitted roots: {resolved}",
            stage="permission",
            details={
                "path": str(resolved),
                "operation": "write",
                "allowed_roots": [str(p) for p in self._write_roots()],
            },
        )

    def check_path_delete(self, path: Path) -> Path:
        """Deletions require write permission AND allow_destructive_fs unless
        the target is strictly inside out_dir/workdir."""
        resolved = self.check_path_write(path)
        return resolved

    # --- shell ----------------------------------------------------------- #

    def check_shell(self, command: str) -> None:
        """Validate a shell command string; raise PermissionDenied on violation."""
        if not self.allow_shell:
            raise PermissionDenied(
                "shell execution is disabled by policy",
                stage="permission",
                details={"command_preview": command[:200], "operation": "shell"},
            )
        for label, pat in _DENY_SHELL_PATTERNS:
            if pat.search(command):
                raise PermissionDenied(
                    f"denied destructive command pattern: {label}",
                    stage="permission",
                    details={"command_preview": command[:200], "pattern": label},
                )
        for token in self.denied_commands:
            if token and token in command:
                raise PermissionDenied(
                    f"command contains denied token: {token!r}",
                    stage="permission",
                    details={"command_preview": command[:200], "token": token},
                )
        if not self.allow_install and _INSTALL_CMD_RE.search(command):
            raise PermissionDenied(
                "package installation is disabled by policy (would risk hanging the run)",
                stage="permission",
                details={"command_preview": command[:200], "operation": "install"},
            )
        if not self.allow_network and _NETWORK_CMD_RE.search(command):
            raise PermissionDenied(
                "network command blocked: network is disabled by policy",
                stage="permission",
                details={"command_preview": command[:200], "operation": "network"},
            )

    # --- network --------------------------------------------------------- #

    def check_network(self, url: str = "") -> None:
        if not self.allow_network:
            raise PermissionDenied(
                "network access is disabled by policy",
                stage="permission",
                details={"url": url[:300], "operation": "network"},
            )
        if url:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https", "file", "ftp", ""):
                raise PermissionDenied(
                    f"disallowed URL scheme: {parsed.scheme!r}",
                    stage="permission",
                    details={"url": url[:300], "scheme": parsed.scheme},
                )

    def is_path_allowed_write(self, path: Path) -> bool:
        try:
            self.check_path_write(path)
            return True
        except PermissionDenied:
            return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "workdir": str(self.workdir),
            "out_dir": str(self.out_dir),
            "allow_network": self.allow_network,
            "allow_shell": self.allow_shell,
            "allow_destructive_fs": self.allow_destructive_fs,
            "allow_install": self.allow_install,
            "denied_commands": list(self.denied_commands),
            "extra_read_roots": [str(p) for p in self.extra_read_roots],
            "extra_write_roots": [str(p) for p in self.extra_write_roots],
        }


def _resolve(path: Path | str) -> Path:
    """Resolve without requiring existence (no strict), normalizing symlinks
    where possible. Falls back to absolute+normpath on error."""
    p = Path(path)
    try:
        return p.resolve()
    except (OSError, RuntimeError):  # pragma: no cover - exotic fs
        return Path(os.path.normpath(os.path.abspath(str(p))))


def _within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _within_any(child: Path, parents: Iterable[Path]) -> bool:
    return any(_within(child, p) for p in parents)
