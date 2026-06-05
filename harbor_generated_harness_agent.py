from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.agent.name import AgentName
from harbor.models.trial.paths import EnvironmentPaths


class GeneratedHarnessAgent(BaseAgent):
    """Harbor agent adapter that runs a generated Harness-Evolve artifact."""

    SUPPORTS_ATIF: bool = False
    SUPPORTS_WINDOWS: bool = False

    def __init__(
        self,
        logs_dir: Path,
        model_name: str | None = None,
        harness_path: str | None = None,
        adapter_path: str | None = None,
        domain: str = "code",
        task_work_dir: str = "/app",
        timeout_sec: int = 900,
        adapter_mode: str = "strict",
        extra_env: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(logs_dir=logs_dir, model_name=model_name, **kwargs)
        self.harness_path = Path(
            harness_path
            or (extra_env or {}).get("GENERATED_HARNESS_PATH")
            or os.environ.get("GENERATED_HARNESS_PATH", "")
        )
        self.adapter_path = Path(
            adapter_path
            or (extra_env or {}).get("GENERATED_HARNESS_ADAPTER")
            or os.environ.get("GENERATED_HARNESS_ADAPTER", "")
        )
        self.domain = domain or (extra_env or {}).get("GENERATED_HARNESS_DOMAIN", "code")
        self.task_work_dir = task_work_dir
        self.timeout_sec = int(timeout_sec)
        self.extra_env = dict(extra_env or {})
        self.adapter_mode = (
            self.extra_env.get("HARNESS_EVAL_ADAPTER_MODE")
            or os.environ.get("HARNESS_EVAL_ADAPTER_MODE")
            or adapter_mode
            or "strict"
        )

    @staticmethod
    def name() -> str:
        return "generated-harness"

    def version(self) -> str:
        return "0.1.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        if not self.harness_path.exists():
            raise FileNotFoundError(f"Generated harness path not found: {self.harness_path}")
        if not self.adapter_path.exists():
            raise FileNotFoundError(f"Generated harness adapter not found: {self.adapter_path}")

        await environment.exec(command="mkdir -p /installed-agent", user="root")
        await environment.upload_file(
            source_path=self.adapter_path,
            target_path="/installed-agent/generated_harness_adapter.py",
        )
        creation_eval_dir = self.adapter_path.parent / "creation_eval"
        if creation_eval_dir.exists():
            await environment.upload_dir(
                source_dir=creation_eval_dir,
                target_dir="/installed-agent/creation_eval",
            )
        await environment.upload_dir(
            source_dir=self.harness_path,
            target_dir="/installed-agent/generated_harness",
        )
        await environment.exec(
            command="chmod +x /installed-agent/generated_harness_adapter.py",
            user="root",
        )

        python_bootstrap = (
            "if ! command -v python3 >/dev/null 2>&1; then "
            "if command -v apt-get >/dev/null 2>&1; then "
            "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-pip; "
            "elif command -v apk >/dev/null 2>&1; then "
            "apk add --no-cache python3 py3-pip; "
            "else echo 'python3 is required but no supported package manager was found' >&2; exit 127; "
            "fi; "
            "fi"
        )
        await environment.exec(command=python_bootstrap, user="root", timeout_sec=600)

        if self.adapter_mode == "permissive":
            install_cmd = (
                "if [ -f /installed-agent/generated_harness/requirements.txt ]; then "
                "PIP_BREAK_SYSTEM_PACKAGES=1 python3 -m pip install --user -q -r /installed-agent/generated_harness/requirements.txt; "
                "fi"
            )
            await environment.exec(command=install_cmd, timeout_sec=240)

    def _runtime_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        passthrough = [
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "MODEL_NAME",
            "MODEL_ID",
            "API_KEY",
            "BASE_URL",
            "SEED2LITE_API_KEY",
            "SEED2LITE_BASE_URL",
            "SEED2LITE_MODEL_ID",
        ]
        for name in passthrough:
            value = self.extra_env.get(name) or os.environ.get(name)
            if value:
                env[name] = value
        return env

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        env_paths = EnvironmentPaths.for_os(environment.os)
        output_dir = str(env_paths.agent_dir / "generated_harness")
        escaped_instruction = shlex.quote(instruction)
        escaped_work_dir = shlex.quote(self.task_work_dir)
        escaped_output_dir = shlex.quote(output_dir)

        await environment.exec(command=f"mkdir -p {escaped_output_dir}", user="root")
        command = (
            "python3 /installed-agent/generated_harness_adapter.py "
            "--harness-path /installed-agent/generated_harness "
            f"--domain {shlex.quote(self.domain)} "
            f"--work-dir {escaped_work_dir} "
            f"--output-dir {escaped_output_dir} "
            f"--timeout {self.timeout_sec} "
            f"--adapter-mode {shlex.quote(self.adapter_mode)} "
            f"{escaped_instruction} "
            f"2>&1 | tee {shlex.quote(str(env_paths.agent_dir / 'generated_harness_stdout.log'))}"
        )
        result = await environment.exec(
            command=command,
            cwd=self.task_work_dir,
            env={**self._runtime_env(), "PYTHONPATH": "/installed-agent"},
            timeout_sec=self.timeout_sec + 60,
        )
        context.metadata = {
            "generated_harness_return_code": result.return_code,
            "generated_harness_domain": self.domain,
            "generated_harness_output_dir": output_dir,
        }
        if result.return_code != 0:
            (self.logs_dir / "generated_harness_failed.txt").write_text(
                f"return_code={result.return_code}\nstdout={result.stdout}\nstderr={result.stderr}",
                encoding="utf-8",
            )
