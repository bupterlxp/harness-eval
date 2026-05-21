"""Main entry point for the Research Agent Harness."""

from __future__ import annotations
import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

from harness.execution import ExecutionLoop, TaskSpec, Result


def parse_task_description(description: str) -> TaskSpec:
    """Parse natural language task description into TaskSpec."""
    questions = []
    lines = description.strip().split("\n")
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#"):
            line = re.sub(r"^[-*•\d.)\]]+\s*", "", line)
            if line:
                questions.append(line)

    if not questions:
        questions = [description.strip()]

    min_sources = 10
    match = re.search(r"(?:min(?:imum)?|at least)\s*(\d+)\s*sources?", description, re.IGNORECASE)
    if not match:
        match = re.search(r"(\d+)\s*(?:min(?:imum)?|at least)\s*sources?", description, re.IGNORECASE)
    if match:
        min_sources = int(match.group(1))

    max_words = 3000
    match = re.search(r"(\d+)\s*(?:max(?:imum)?|words?|max\s*words?)", description, re.IGNORECASE)
    if match:
        max_words = int(match.group(1))

    max_hops = 3
    match = re.search(r"(\d+)\s*(?:hops?|iterations?|rounds?)", description, re.IGNORECASE)
    if match:
        max_hops = int(match.group(1))

    required_sections = ["Introduction", "Findings", "Conclusion"]
    section_patterns = [
        r"sections?:\s*([^.]+)",
        r"include\s*(?:sections?)?:\s*([^.]+)",
        r"required\s*sections?:\s*([^.]+)",
    ]
    for pattern in section_patterns:
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            section_text = match.group(1)
            sections = [s.strip() for s in re.split(r"[,;]", section_text) if s.strip()]
            if sections:
                required_sections = sections
            break

    constraints = []
    constraint_patterns = [
        r"constraint:\s*([^.]+)",
        r"must\s+([^.]+)",
        r"should\s+([^.]+)",
    ]
    for pattern in constraint_patterns:
        for match in re.finditer(pattern, description, re.IGNORECASE):
            constraints.append(match.group(1).strip())

    return TaskSpec(
        research_questions=questions,
        min_sources=min_sources,
        max_words=max_words,
        required_sections=required_sections,
        max_hops=max_hops,
        constraints=constraints,
    )


async def run_research(task_spec: TaskSpec) -> Result:
    """Run the research pipeline."""
    executor = ExecutionLoop(task_spec)
    return await executor.run()


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Research Agent Harness - Autonomous deep research",
    )
    parser.add_argument(
        "-p", "--prompt",
        type=str,
        required=True,
        help="Natural language task description",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./output",
        help="Output directory for results",
    )
    parser.add_argument(
        "--min-sources",
        type=int,
        default=None,
        help="Minimum number of sources to gather",
    )
    parser.add_argument(
        "--max-words",
        type=int,
        default=None,
        help="Maximum words in the report",
    )
    parser.add_argument(
        "--max-hops",
        type=int,
        default=None,
        help="Maximum multi-hop iterations",
    )
    parser.add_argument(
        "--sections",
        type=str,
        nargs="+",
        default=None,
        help="Required sections in the report",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON",
    )

    args = parser.parse_args()

    task_spec = parse_task_description(args.prompt)
    task_spec.output_dir = args.output_dir

    if args.min_sources is not None:
        task_spec.min_sources = args.min_sources
    if args.max_words is not None:
        task_spec.max_words = args.max_words
    if args.max_hops is not None:
        task_spec.max_hops = args.max_hops
    if args.sections is not None:
        task_spec.required_sections = args.sections

    Path(task_spec.output_dir).mkdir(parents=True, exist_ok=True)

    result = asyncio.run(run_research(task_spec))

    result_path = Path(task_spec.output_dir) / "result.json"
    with open(result_path, "w") as f:
        json.dump(result.to_dict(), f, indent=2)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"Status: {result.status}")
        print(f"Report: {result.report_path}")
        print(f"Sources: {len(result.sources)}")
        print(f"Trajectory: {result.trajectory}")
        if result.gaps:
            print(f"Gaps: {result.gaps}")

    return 0 if result.status in ("success", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
