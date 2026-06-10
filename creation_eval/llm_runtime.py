from __future__ import annotations

import os
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from creation_eval.model_aliases import resolve_model_alias


def _port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def resolve_provider_proxy_port(preferred: int) -> int:
    """Use the preferred provider-proxy port unless it (or the metrics relay
    port right below it) is taken — e.g. by the creation container's own
    Claude Code proxy on 3457/3458. Falling back to an ephemeral free port
    lets dev-BMK eval proxies coexist with the creation proxy."""
    if _port_is_free(preferred) and _port_is_free(max(1, preferred - 1)):
        return preferred
    return _pick_free_port()


@dataclass
class LLMRuntime:
    process: subprocess.Popen | None = None
    log_handle: object | None = None
    log_path: Path | None = None

    def close(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log_handle:
            try:
                self.log_handle.close()
            except Exception:
                pass


def normalize_chat_completions_url(url: str) -> str:
    url = url.rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    return url + "/chat/completions"


def normalize_openai_base_url(url: str) -> str:
    url = url.rstrip("/")
    suffix = "/chat/completions"
    if url.endswith(suffix):
        return url[: -len(suffix)]
    return url


def is_exact_provider_endpoint(url: str) -> bool:
    lower = url.lower()
    return "/v2/crawl" in lower


def configure_eval_llm(
    *,
    harness_eval_root: Path,
    base_url: str | None = None,
    api_key: str | None = None,
    model_name: str | None = None,
    reasoning_effort: str | None = None,
    provider_proxy: bool = True,
    provider_proxy_host: str = "0.0.0.0",
    provider_proxy_port: int = 3458,
    log_path: Path | None = None,
) -> LLMRuntime:
    """Configure env for the LLM used by generated harnesses during eval.

    Host-side judges use OPENAI_BASE_URL. Docker-contained benchmark tasks use
    CONTAINER_OPENAI_BASE_URL, which avoids pointing containers at their own
    localhost when a local provider proxy is used.
    """
    resolved_model = resolve_model_alias(model_name or os.environ.get("EVAL_MODEL_NAME") or "") or ""
    resolved_base_url = base_url or os.environ.get("EVAL_BASE_URL") or ""
    resolved_api_key = api_key or os.environ.get("EVAL_API_KEY") or ""
    resolved_effort = reasoning_effort or os.environ.get("EVAL_REASONING_EFFORT") or ""

    if not any([resolved_model, resolved_base_url, resolved_api_key, resolved_effort]):
        return LLMRuntime()
    missing = [
        name
        for name, value in {
            "eval model": resolved_model,
            "eval base url": resolved_base_url,
            "eval api key": resolved_api_key,
        }.items()
        if not value
    ]
    if missing:
        raise ValueError("Missing eval LLM config: " + ", ".join(missing))

    if provider_proxy:
        # OpenAI-compatible providers want /chat/completions. The TikTok/ModelHub
        # Anthropic endpoint is native Claude Messages API; model-proxy translates
        # OpenAI chat requests to /v1/messages itself, so do not append the
        # OpenAI suffix here.
        if "/anthropic" in resolved_base_url.lower() or is_exact_provider_endpoint(resolved_base_url):
            upstream_url = resolved_base_url.rstrip("/")
        else:
            upstream_url = normalize_chat_completions_url(resolved_base_url)
        provider_proxy_port = resolve_provider_proxy_port(provider_proxy_port)
        host_base = f"http://127.0.0.1:{provider_proxy_port}/v1"
        container_base = f"http://host.docker.internal:{provider_proxy_port}/v1"
        os.environ.update(
            {
                "OPENAI_BASE_URL": host_base,
                "BASE_URL": host_base,
                "OPENAI_API_KEY": "proxy-placeholder",
                "API_KEY": "proxy-placeholder",
                "MODEL_NAME": resolved_model,
                "OPENAI_MODEL": resolved_model,
                "MODEL_ID": resolved_model,
                "SEED2LITE_API_KEY": "proxy-placeholder",
                "SEED2LITE_BASE_URL": host_base,
                "SEED2LITE_CHAT_COMPLETIONS_URL_HTTP": host_base.rstrip("/") + "/chat/completions",
                "SEED2LITE_MODEL_ID": resolved_model,
                "SEED2LITE_CODE_MODEL_ID": resolved_model,
                "TEST_API_KEY": "proxy-placeholder",
                "TEST_API_URL": host_base.rstrip("/") + "/chat/completions",
                "JUDGE_API_KEY": "proxy-placeholder",
                "JUDGE_API_URL": host_base.rstrip("/") + "/chat/completions",
                "MOONSHOT_API_KEY": "proxy-placeholder",
                "MOONSHOT_BASE_URL": host_base,
                "KIMI_WRITER_MODEL": resolved_model,
                "CONTAINER_OPENAI_BASE_URL": container_base,
                "CONTAINER_BASE_URL": container_base,
                "CONTAINER_OPENAI_API_KEY": "proxy-placeholder",
                "CONTAINER_API_KEY": "proxy-placeholder",
                "CONTAINER_MODEL_NAME": resolved_model,
                "CONTAINER_MODEL_ID": resolved_model,
                "CONTAINER_SEED2LITE_API_KEY": "proxy-placeholder",
                "CONTAINER_SEED2LITE_BASE_URL": container_base,
                "CONTAINER_SEED2LITE_CHAT_COMPLETIONS_URL_HTTP": container_base.rstrip("/") + "/chat/completions",
                "CONTAINER_SEED2LITE_MODEL_ID": resolved_model,
                "DACOMP_JUDGE_MODEL_CONFIG": "ep-20260214145701-frz7j",
            }
        )
        proxy_env = os.environ.copy()
        proxy_env.update(
            {
                "UPSTREAM_BASE_URL": upstream_url,
                "UPSTREAM_API_KEY": resolved_api_key,
                "MODEL_NAME": resolved_model,
                "PROXY_PORT": str(max(1, provider_proxy_port - 1)),
                "PROVIDER_PROXY_HOST": provider_proxy_host,
                "PROVIDER_PROXY_PORT": str(provider_proxy_port),
                "OPENROUTER_VERBOSITY": resolved_effort,
                "OPENROUTER_REASONING_ENABLED": "true" if resolved_effort else "",
            }
        )
        if log_path is None:
            log_path = harness_eval_root / "eval_provider_proxy.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # The proxy writes metrics relative to WORKSPACE/cwd by default; inside
        # creation containers harness-eval is mounted read-only, so point the
        # metrics file at the writable eval output directory explicitly.
        proxy_env["METRICS_PATH"] = str(log_path.parent / "eval_proxy_metrics.json")
        proxy_env["WORKSPACE"] = str(log_path.parent)
        # Creation containers may run their own proxy in Anthropic passthrough
        # mode and that env var would be inherited here. The eval proxy serves
        # OpenAI-shaped requests from generated harnesses, so it must use the
        # converting anthropic-native handler instead of verbatim passthrough.
        proxy_env["PROVIDER_ANTHROPIC_PASSTHROUGH"] = ""
        log_handle = log_path.open("a", encoding="utf-8")
        process = subprocess.Popen(
            ["node", str(harness_eval_root / "model-proxy.js")],
            cwd=harness_eval_root,
            env=proxy_env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        time.sleep(1.0)
        if process.poll() is not None:
            log_handle.close()
            raise RuntimeError(f"Eval provider proxy exited early. See {log_path}")
        return LLMRuntime(process=process, log_handle=log_handle, log_path=log_path)

    base = normalize_openai_base_url(resolved_base_url)
    os.environ.update(
        {
            "OPENAI_BASE_URL": base,
            "BASE_URL": base,
            "OPENAI_API_KEY": resolved_api_key,
            "API_KEY": resolved_api_key,
            "MODEL_NAME": resolved_model,
            "OPENAI_MODEL": resolved_model,
            "MODEL_ID": resolved_model,
            "SEED2LITE_API_KEY": resolved_api_key,
            "SEED2LITE_BASE_URL": base,
            "SEED2LITE_CHAT_COMPLETIONS_URL_HTTP": base.rstrip("/") + "/chat/completions",
            "SEED2LITE_MODEL_ID": resolved_model,
            "SEED2LITE_CODE_MODEL_ID": resolved_model,
            "TEST_API_KEY": resolved_api_key,
            "TEST_API_URL": base.rstrip("/") + "/chat/completions",
            "JUDGE_API_KEY": resolved_api_key,
            "JUDGE_API_URL": base.rstrip("/") + "/chat/completions",
            "MOONSHOT_API_KEY": resolved_api_key,
            "MOONSHOT_BASE_URL": base,
            "KIMI_WRITER_MODEL": resolved_model,
            "CONTAINER_OPENAI_BASE_URL": base,
            "CONTAINER_BASE_URL": base,
            "CONTAINER_OPENAI_API_KEY": resolved_api_key,
            "CONTAINER_API_KEY": resolved_api_key,
            "CONTAINER_MODEL_NAME": resolved_model,
            "CONTAINER_MODEL_ID": resolved_model,
            "CONTAINER_SEED2LITE_API_KEY": resolved_api_key,
            "CONTAINER_SEED2LITE_BASE_URL": base,
            "CONTAINER_SEED2LITE_CHAT_COMPLETIONS_URL_HTTP": base.rstrip("/") + "/chat/completions",
            "CONTAINER_SEED2LITE_MODEL_ID": resolved_model,
            "DACOMP_JUDGE_MODEL_CONFIG": "ep-20260214145701-frz7j",
        }
    )
    return LLMRuntime()
