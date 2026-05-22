from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from .schema import HarnessRunResult
from .utils import best_python_bin, copytree_filtered, run_command, write_json


TEXT_SUFFIXES = {".md", ".txt", ".json"}


REAL_SEARCH_SITECUSTOMIZE = r'''
"""Runtime search-tool patch for generated research harnesses.

This file is written into the temporary generated-harness workspace by the
adapter. Python imports sitecustomize automatically, so the generated harness
keeps its own control flow while the benchmark supplies a real search backend
instead of accepting mock/simulated search implementations.
"""

import html
import json
import os
import re
import urllib.parse
import urllib.error
import urllib.request


def _post_json(url, payload, headers=None, timeout=30):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _serper_search(query, max_results):
    api_key = os.environ.get("SERPER_KEY_ID") or os.environ.get("SEARCH_API_KEY")
    if not api_key:
        return None
    data = _post_json(
        "https://google.serper.dev/search",
        {"q": query, "num": max_results},
        headers={"X-API-KEY": api_key},
    )
    results = []
    answer_box = data.get("answerBox") or {}
    if answer_box:
        answer = answer_box.get("answer") or answer_box.get("snippet") or answer_box.get("snippetHighlighted")
        if answer:
            results.append(
                {
                    "title": answer_box.get("title") or "Answer Box",
                    "url": answer_box.get("link") or "",
                    "link": answer_box.get("link") or "",
                    "snippet": str(answer),
                    "content": str(answer),
                    "source": "serper",
                }
            )
    knowledge_graph = data.get("knowledgeGraph") or {}
    if knowledge_graph:
        description = knowledge_graph.get("description")
        if description:
            results.append(
                {
                    "title": knowledge_graph.get("title") or "Knowledge Graph",
                    "url": knowledge_graph.get("website") or "",
                    "link": knowledge_graph.get("website") or "",
                    "snippet": str(description),
                    "content": str(description),
                    "source": "serper",
                }
            )
    for item in data.get("organic") or []:
        link = item.get("link") or item.get("url") or ""
        snippet = item.get("snippet") or item.get("description") or ""
        results.append(
            {
                "title": item.get("title") or link,
                "url": link,
                "link": link,
                "snippet": snippet,
                "content": snippet,
                "source": "serper",
            }
        )
        if len(results) >= max_results:
            break
    return results[:max_results]


def _tavily_search(query, max_results):
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return None
    data = _post_json(
        "https://api.tavily.com/search",
        {
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
        },
    )
    results = []
    for item in data.get("results") or []:
        link = item.get("url") or ""
        content = item.get("content") or item.get("snippet") or ""
        results.append(
            {
                "title": item.get("title") or link,
                "url": link,
                "link": link,
                "snippet": content,
                "content": content,
                "source": "tavily",
                "score": item.get("score"),
            }
        )
    return results[:max_results]


def _duckduckgo_html_search(query, max_results):
    params = urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(
        "https://html.duckduckgo.com/html/?" + params,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; harness-eval/0.1; +https://github.com)",
            "Accept": "text/html,application/xhtml+xml",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=float(os.environ.get("HARNESS_EVAL_SEARCH_TIMEOUT_SECONDS", "10"))) as response:
        page = response.read().decode("utf-8", errors="replace")
    anchor_pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    snippet_pattern = re.compile(
        r'<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    snippets = [html.unescape(re.sub(r"<[^>]+>", " ", item).strip()) for item in snippet_pattern.findall(page)]
    results = []
    for idx, match in enumerate(anchor_pattern.finditer(page)):
        href = html.unescape(match.group("href"))
        title = html.unescape(re.sub(r"<[^>]+>", " ", match.group("title")).strip())
        parsed = urllib.parse.urlparse(href)
        qs = urllib.parse.parse_qs(parsed.query)
        link = qs.get("uddg", [href])[0]
        if link.startswith("//"):
            link = "https:" + link
        snippet = snippets[idx] if idx < len(snippets) else ""
        if not link or "duckduckgo.com/y.js" in link:
            continue
        results.append(
            {
                "title": title or link,
                "url": link,
                "link": link,
                "snippet": snippet,
                "content": snippet,
                "source": "duckduckgo_html",
            }
        )
        if len(results) >= max_results:
            break
    return results[:max_results]


def _bing_html_search(query, max_results):
    params = urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(
        "https://www.bing.com/search?" + params,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; harness-eval/0.1; +https://github.com)",
            "Accept": "text/html,application/xhtml+xml",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=float(os.environ.get("HARNESS_EVAL_SEARCH_TIMEOUT_SECONDS", "10"))) as response:
        page = response.read().decode("utf-8", errors="replace")
    block_pattern = re.compile(r'<li[^>]+class="b_algo"[^>]*>(?P<block>.*?)</li>', re.IGNORECASE | re.DOTALL)
    link_pattern = re.compile(r'<h2[^>]*>\s*<a[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>', re.IGNORECASE | re.DOTALL)
    snippet_pattern = re.compile(r'<p[^>]*>(?P<snippet>.*?)</p>', re.IGNORECASE | re.DOTALL)
    results = []
    for block_match in block_pattern.finditer(page):
        block = block_match.group("block")
        link_match = link_pattern.search(block)
        if not link_match:
            continue
        link = html.unescape(link_match.group("href"))
        title = html.unescape(re.sub(r"<[^>]+>", " ", link_match.group("title")).strip())
        snippet_match = snippet_pattern.search(block)
        snippet = ""
        if snippet_match:
            snippet = html.unescape(re.sub(r"<[^>]+>", " ", snippet_match.group("snippet")).strip())
        results.append(
            {
                "title": title or link,
                "url": link,
                "link": link,
                "snippet": snippet,
                "content": snippet,
                "source": "bing_html",
            }
        )
        if len(results) >= max_results:
            break
    return results[:max_results]


def _real_search(query, max_results=10):
    max_results = int(max_results or 10)
    errors = []
    for provider in (_serper_search, _tavily_search, _bing_html_search, _duckduckgo_html_search):
        try:
            results = provider(query, max_results)
            if results:
                return results
        except Exception as exc:  # noqa: BLE001 - surfaced to generated harness
            errors.append(f"{provider.__name__}: {type(exc).__name__}: {exc}")
    raise RuntimeError("Real search provider failed: " + "; ".join(errors))


async def _async_domain_web_search(self, query, max_results=10):
    return _real_search(query, max_results)


async def _async_web_search_tool_search(self, query, max_results=None):
    return _real_search(query, max_results or getattr(self, "max_results", 10))


def _patch_opus_style_domain_tools():
    try:
        from harness.domain import tools as domain_tools

        if hasattr(domain_tools, "DomainTools"):
            original_decompose = domain_tools.DomainTools.decompose_questions

            async def _limited_decompose_questions(self, *args, **kwargs):
                queries = await original_decompose(self, *args, **kwargs)
                try:
                    max_queries = int(os.environ.get("HARNESS_EVAL_RESEARCH_MAX_QUERIES", "2"))
                except ValueError:
                    max_queries = 2
                return queries[:max_queries] if max_queries > 0 else queries

            domain_tools.DomainTools.decompose_questions = _limited_decompose_questions
            domain_tools.DomainTools.web_search = _async_domain_web_search
    except Exception:
        pass


def _patch_doubao_style_tools():
    try:
        from harness import tools as harness_tools

        if hasattr(harness_tools, "WebSearchTool"):
            harness_tools.WebSearchTool.search = _async_web_search_tool_search
    except Exception:
        pass


if os.environ.get("HARNESS_EVAL_ENABLE_REAL_SEARCH") == "1":
    _patch_opus_style_domain_tools()
    _patch_doubao_style_tools()
'''


def _latest_text_file(root: Path, started_at: float) -> Path | None:
    candidates: list[Path] = []
    if not root.exists():
        return None
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if path.name in {"CLAUDE.md", "metrics.json", "meta.json"}:
            continue
        try:
            if path.stat().st_mtime >= started_at - 1:
                candidates.append(path)
        except OSError:
            continue
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _install_real_search_patch(workspace: Path) -> None:
    (workspace / "sitecustomize.py").write_text(REAL_SEARCH_SITECUSTOMIZE, encoding="utf-8")


def _install_requirements(workspace: Path, python_bin: str, timeout: int) -> dict[str, Any] | None:
    requirements = workspace / "requirements.txt"
    if not requirements.is_file():
        return None
    env = os.environ.copy()
    env.setdefault("PIP_BREAK_SYSTEM_PACKAGES", "1")
    result = run_command(
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
        cwd=workspace,
        env=env,
        timeout=max(timeout, 300),
    )
    return {
        "command": [python_bin, "-m", "pip", "install", "-r", str(requirements)],
        "returncode": result.returncode,
        "elapsed_sec": result.elapsed_sec,
        "stdout_tail": result.stdout[-4000:],
        "stderr_tail": result.stderr[-4000:],
    }


def _commands_for_domain(
    domain: str,
    python_bin: str,
    prompt: str,
    harness_workspace: Path,
    task_work_dir: Path,
    output_dir: Path,
) -> list[list[str]]:
    sample_dir = harness_workspace / "samples"
    commands: list[list[str]] = [
        [python_bin, "-m", "harness", "-p", prompt, "--output-dir", str(output_dir)],
        [python_bin, "-m", "harness.cli", "-p", prompt, "--output-dir", str(output_dir)],
    ]
    if domain == "writing":
        commands.extend(
            [
                [python_bin, "-m", "harness", prompt, "--output", str(output_dir / "response.md")],
                [python_bin, "-m", "harness", prompt, "--auto-approve"],
                [python_bin, "-m", "harness.cli", prompt, "--output", str(output_dir / "response.md")],
                [python_bin, "-m", "harness.cli", prompt],
            ]
        )
    elif domain == "data_analysis":
        data_candidates = sorted(task_work_dir.rglob("*.csv")) + sorted(task_work_dir.rglob("*.sqlite"))
        data_file = data_candidates[0] if data_candidates else sample_dir / "sales_data.csv"
        commands.extend(
            [
                [python_bin, "-m", "harness", str(data_file), "--goal", prompt, "--auto-run", "--output", str(output_dir)],
                [python_bin, "-m", "harness.cli", str(data_file), "--goal", prompt, "--auto-run", "--output", str(output_dir)],
                [
                    python_bin,
                    "-m",
                    "harness",
                    "analyze",
                    str(data_file),
                    "--goal",
                    prompt,
                    "--requirements",
                    "produce a concise report",
                    "--output-dir",
                    str(output_dir),
                ],
            ]
        )
    elif domain == "code":
        commands.extend(
            [
                [
                    python_bin,
                    "-m",
                    "harness",
                    "-p",
                    prompt,
                    "--workdir",
                    str(task_work_dir),
                    "--output-dir",
                    str(output_dir),
                ],
                [
                    python_bin,
                    "-m",
                    "harness.cli",
                    "-p",
                    prompt,
                    "--workdir",
                    str(task_work_dir),
                    "--output-dir",
                    str(output_dir),
                ],
                [
                    python_bin,
                    "-m",
                    "harness",
                    "run",
                    "-p",
                    prompt,
                    "--workdir",
                    str(task_work_dir),
                    "--output-dir",
                    str(output_dir),
                ],
                [
                    python_bin,
                    "-m",
                    "harness.cli",
                    "run",
                    "-p",
                    prompt,
                    "--workdir",
                    str(task_work_dir),
                    "--output-dir",
                    str(output_dir),
                ],
                [
                    python_bin,
                    "-m",
                    "harness",
                    "-p",
                    prompt,
                    "--work-dir",
                    str(task_work_dir),
                    "--output-dir",
                    str(output_dir),
                ],
                [
                    python_bin,
                    "-m",
                    "harness.cli",
                    "-p",
                    prompt,
                    "--work-dir",
                    str(task_work_dir),
                    "--output-dir",
                    str(output_dir),
                ],
                [
                    python_bin,
                    "-m",
                    "harness",
                    "run",
                    "-p",
                    prompt,
                    "--work-dir",
                    str(task_work_dir),
                    "--output-dir",
                    str(output_dir),
                ],
                [
                    python_bin,
                    "-m",
                    "harness",
                    "run",
                    "--prompt",
                    prompt,
                    "--work-dir",
                    str(task_work_dir),
                    "--output-dir",
                    str(output_dir),
                ],
                [
                    python_bin,
                    "-m",
                    "harness.cli",
                    "run",
                    "-p",
                    prompt,
                    "--work-dir",
                    str(task_work_dir),
                    "--output-dir",
                    str(output_dir),
                ],
                [
                    python_bin,
                    "-m",
                    "harness.cli",
                    "run",
                    "--prompt",
                    prompt,
                    "--work-dir",
                    str(task_work_dir),
                    "--output-dir",
                    str(output_dir),
                ],
            ]
        )
    elif domain == "research":
        task_json = output_dir / "research_task.json"
        write_json(
            task_json,
            {
                "topic": prompt[:200],
                "questions": [prompt],
                "constraints": {
                    "required_sections": ["answer"],
                    "min_sources": 3,
                    "max_report_length_words": 1200,
                },
                "requirements": ["include citations when evidence is available"],
            },
        )
        commands.extend(
            [
                [
                    python_bin,
                    "-m",
                    "harness.cli",
                    str(task_json),
                    "-o",
                    str(output_dir / "report.md"),
                    "-t",
                    str(output_dir / "trajectory.jsonl"),
                    "--max-hops",
                    "1",
                ],
                [python_bin, "-m", "harness", str(task_json), "-o", str(output_dir / "report.md"), "-t", str(output_dir / "trajectory.jsonl")],
                [python_bin, "-m", "harness.cli", "--topic", prompt, "--questions", prompt, "--output-dir", str(output_dir)],
                [python_bin, "-m", "harness", "--topic", prompt, "--questions", prompt],
            ]
        )
    elif domain == "browser":
        scenario = sample_dir / "task_scenarios.json"
        commands.extend(
            [
                [python_bin, "-m", "harness", str(scenario), "--headless"],
                [python_bin, "-m", "harness", "--scenario", str(scenario), "--headless"],
                [python_bin, "-m", "harness", "--demo", "--headless"],
            ]
        )
    return commands


def run_generated_harness(
    harness_path: Path,
    domain: str,
    prompt: str,
    output_dir: Path,
    *,
    task_work_dir: Path | None = None,
    python_bin: str | None = None,
    timeout: int = 900,
) -> HarnessRunResult:
    python_bin = best_python_bin(python_bin)
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = output_dir / "adapter_stdout.log"
    stderr_path = output_dir / "adapter_stderr.log"
    raw_result_path = output_dir / "adapter_result.json"
    started_at = time.time()

    with tempfile.TemporaryDirectory(prefix="generated_harness_") as tmp:
        workspace = Path(tmp) / "artifact"
        copytree_filtered(harness_path, workspace)
        if domain == "research":
            _install_real_search_patch(workspace)
        task_work_dir = task_work_dir.resolve() if task_work_dir else workspace
        run_output_dir = workspace / "adapter_output"
        run_output_dir.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["PYTHONPATH"] = str(workspace) + os.pathsep + env.get("PYTHONPATH", "")
        env.setdefault("OPENAI_BASE_URL", env.get("SEED2LITE_BASE_URL", env.get("BASE_URL", "")))
        env.setdefault("OPENAI_API_KEY", env.get("SEED2LITE_API_KEY", env.get("API_KEY", "")))
        env.setdefault("MODEL_NAME", env.get("SEED2LITE_MODEL_ID", env.get("MODEL_ID", "")))
        if domain == "research":
            env["HARNESS_EVAL_ENABLE_REAL_SEARCH"] = "1"
            env.setdefault("HARNESS_EVAL_RESEARCH_MAX_QUERIES", "2")
            env.setdefault("HARNESS_EVAL_SEARCH_TIMEOUT_SECONDS", "10")

        attempts: list[dict[str, Any]] = []
        install_attempt = _install_requirements(workspace, python_bin, timeout)
        if install_attempt:
            attempts.append({"phase": "install_requirements", **install_attempt})
            if install_attempt["returncode"] != 0:
                write_json(raw_result_path, {"status": "failed", "domain": domain, "attempts": attempts})
                return HarnessRunResult(
                    status="adapter_failed",
                    score=0.0,
                    pass_rate=0.0,
                    score_breakdown={"adapter_smoke": True},
                    stdout_path=str(stdout_path),
                    stderr_path=str(stderr_path),
                    raw_result_path=str(raw_result_path),
                    error="Generated harness requirements installation failed",
                )
        for command in _commands_for_domain(domain, python_bin, prompt, workspace, task_work_dir, run_output_dir):
            result = run_command(command, cwd=task_work_dir, env=env, timeout=timeout)
            attempts.append(
                {
                    "command": command,
                    "returncode": result.returncode,
                    "elapsed_sec": result.elapsed_sec,
                    "stdout_tail": result.stdout[-4000:],
                    "stderr_tail": result.stderr[-4000:],
                }
            )
            stdout_path.write_text(result.stdout, encoding="utf-8")
            stderr_path.write_text(result.stderr, encoding="utf-8")
            if result.returncode == 0:
                latest = _latest_text_file(run_output_dir, started_at) or _latest_text_file(workspace, started_at)
                response_text = ""
                selected_path = ""
                if latest:
                    selected_path = str(latest)
                    try:
                        response_text = latest.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        response_text = ""
                if not response_text.strip():
                    response_text = result.stdout.strip()

                response_path = output_dir / "response.md"
                response_path.write_text(response_text, encoding="utf-8")
                artifacts_dir = output_dir / "artifacts"
                if run_output_dir.exists():
                    if artifacts_dir.exists():
                        shutil.rmtree(artifacts_dir)
                    shutil.copytree(run_output_dir, artifacts_dir, dirs_exist_ok=True)
                write_json(
                    raw_result_path,
                    {
                        "status": "success",
                        "domain": domain,
                        "selected_file": str(response_path),
                        "source_selected_file": selected_path,
                        "artifacts_dir": str(artifacts_dir),
                        "response_chars": len(response_text),
                        "attempts": attempts,
                    },
                )
                return HarnessRunResult(
                    status="success",
                    score=1.0,
                    pass_rate=1.0,
                    score_breakdown={"adapter_smoke": True, "response_chars": len(response_text)},
                    stdout_path=str(stdout_path),
                    stderr_path=str(stderr_path),
                    raw_result_path=str(raw_result_path),
                )

        write_json(raw_result_path, {"status": "failed", "domain": domain, "attempts": attempts})
        return HarnessRunResult(
            status="adapter_failed",
            score=0.0,
            pass_rate=0.0,
            score_breakdown={"adapter_smoke": True},
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            raw_result_path=str(raw_result_path),
            error="All generated harness invocation patterns failed",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="CLI shim for generated harness artifacts.")
    parser.add_argument("prompt", nargs="*", help="Prompt passed by a downstream benchmark.")
    parser.add_argument("--harness-path", default=os.environ.get("GENERATED_HARNESS_PATH"))
    parser.add_argument("--domain", default=os.environ.get("GENERATED_HARNESS_DOMAIN", "writing"))
    parser.add_argument("--output-dir", default=os.environ.get("GENERATED_HARNESS_ADAPTER_OUTPUT_DIR"))
    parser.add_argument("--work-dir", default=os.environ.get("GENERATED_HARNESS_TASK_WORK_DIR"))
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("GENERATED_HARNESS_TIMEOUT", "900")))
    args = parser.parse_args()

    if not args.harness_path:
        print("GENERATED_HARNESS_PATH or --harness-path is required", file=sys.stderr)
        raise SystemExit(2)
    prompt = " ".join(args.prompt).strip()
    if not prompt:
        prompt = sys.stdin.read()
    output_dir = Path(args.output_dir or tempfile.mkdtemp(prefix="generated_harness_adapter_"))
    result = run_generated_harness(
        Path(args.harness_path),
        args.domain,
        prompt,
        output_dir,
        task_work_dir=Path(args.work_dir) if args.work_dir else None,
        python_bin=os.environ.get("HARNESS_EVAL_PYTHON") or sys.executable,
        timeout=args.timeout,
    )

    payload = {}
    raw_result = Path(result.raw_result_path)
    if raw_result.exists():
        try:
            payload = json.loads(raw_result.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
    selected_file = payload.get("selected_file")
    response = ""
    if selected_file and Path(selected_file).exists():
        response = Path(selected_file).read_text(encoding="utf-8", errors="replace")
    if not response and Path(result.stdout_path).exists():
        response = Path(result.stdout_path).read_text(encoding="utf-8", errors="replace")

    project_dir = output_dir.resolve()
    response_path = output_dir / "response.md"
    response_path.write_text(response, encoding="utf-8")
    print(f"Successfully created project folder at '{project_dir}'")
    print(f"Successfully created file '{response_path.name}'")
    print(response)
    print(
        "KIMI_WRITER_USAGE_JSON: "
        + json.dumps({"scope": "final", "totals": {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}})
    )
    raise SystemExit(0 if result.status == "success" else 1)


if __name__ == "__main__":
    main()
