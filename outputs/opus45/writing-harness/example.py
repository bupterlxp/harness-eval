#!/usr/bin/env python3
"""
example.py - Example usage of the Short Story Writing Harness

Demonstrates running the FEATURE_EXAMPLE task (Tell-Tale Heart style story).
"""

import os
import sys
from pathlib import Path

from harness.core import create_harness

IDEAL_INPUT = """
体裁:心理惊悚 / 哥特短篇
篇幅:约 2000–2500 词(英文)
视角:第一人称不可靠叙述者
核心张力:叙述者向读者倾诉自己策划并实施的一桩谋杀,并坚称自己神志清醒
关键约束:
  - 杀机来自一个具体而非理性的执念物(如身体某部位、器官、物件)
  - 必须有"延宕铺垫(七夜窥伺)→ 第八夜爆发"的双段式时间结构
  - 杀人后必须有"看似完美的隐藏",但被一种感官信号(声/影/气味)逐渐瓦解
  - 结尾必须是叙述者在外人面前主动崩溃、自我招供
风格要求:
  - 大量破折号、感叹号、词语重复("louder, louder, louder")
  - 直接呼告读者("you fancy me mad")
  - 以听觉意象为主导(心跳、怀表、墙中虫鸣构成隐喻链)
"""


def main():
    """Run the example task"""
    required_env = ["OPENAI_BASE_URL", "OPENAI_API_KEY", "MODEL_NAME"]
    missing = [v for v in required_env if not os.environ.get(v)]

    if missing:
        print("Missing required environment variables:")
        for v in missing:
            print(f"  - {v}")
        print("\nSet these before running:")
        print("  export OPENAI_BASE_URL=http://127.0.0.1:3457/v1")
        print("  export OPENAI_API_KEY=your-key")
        print("  export MODEL_NAME=gpt-4")
        sys.exit(1)

    print("=" * 60)
    print("SHORT STORY WRITING HARNESS - EXAMPLE")
    print("=" * 60)
    print()
    print("Task: Generate a Tell-Tale Heart style psychological thriller")
    print()

    def output_handler(msg: str):
        print(f"[harness] {msg}")

    def approval_handler(tool_name: str, args: dict) -> bool:
        print(f"\n[APPROVAL] Tool: {tool_name}")
        print(f"           Args: {list(args.keys())}")
        response = input("Approve? (y/n): ").strip().lower()
        return response in ("y", "yes", "")

    auto_approve = "--auto-approve" in sys.argv

    harness = create_harness(
        on_output=output_handler,
        approval_handler=None if auto_approve else approval_handler,
        auto_approve=auto_approve
    )

    print("\nStarting generation...")
    print("-" * 60)

    final = harness.run(IDEAL_INPUT)

    print("-" * 60)
    print(f"\nFinal state: {final.current_state.value}")

    if final.final_draft:
        word_count = len(final.final_draft.split())
        print(f"Generated: {word_count} words")

        output_path = Path("output_story.txt")
        with open(output_path, "w") as f:
            f.write(final.final_draft)
        print(f"Saved to: {output_path}")

        print("\n" + "=" * 60)
        print("PREVIEW (first 500 chars)")
        print("=" * 60)
        print(final.final_draft[:500] + "..." if len(final.final_draft) > 500 else final.final_draft)

    trajectory = harness.get_trajectory()
    if trajectory:
        print(f"\nTrajectory: {trajectory.output_path}")

        summary = trajectory.export_summary()
        print(f"Steps: {summary['total_steps']}")
        print(f"Tool calls: {summary['tool_calls']}")
        print(f"Errors: {summary['errors']}")

    sample_path = Path("./samples/the_tell_tale_heart.txt")
    if sample_path.exists() and final.final_draft:
        print("\n" + "=" * 60)
        print("COMPARISON WITH SAMPLE")
        print("=" * 60)

        report = harness.compare_with_sample(sample_path)
        print(f"\nOverall alignment: {report.overall_alignment_score:.1%}")
        print(report.summary)

        if report.structure_comparisons:
            print("\nStructure:")
            for comp in report.structure_comparisons:
                status = "✓" if comp.aligned else "✗"
                print(f"  {status} {comp.aspect}: {comp.actual_value} (sample: {comp.sample_value})")

        if report.style_comparisons:
            print("\nStyle:")
            for comp in report.style_comparisons:
                status = "✓" if comp.aligned else "✗"
                print(f"  {status} {comp.aspect}: {comp.actual_value}")


if __name__ == "__main__":
    main()
