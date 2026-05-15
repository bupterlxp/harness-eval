#!/usr/bin/env python3
"""Example usage of the short story generation harness"""

from harness import Harness, TaskSpec, StoryGenre, Perspective
from harness.domain.tools import *
import os

# Set up environment variables for LLM
os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:3457/v1"
os.environ["OPENAI_API_KEY"] = "dummy_key"
os.environ["MODEL_NAME"] = "gpt-3.5-turbo"

def example_basic_usage():
    """Basic example of using the harness"""
    print("=== Basic Harness Usage Example ===\n")

    # Create a harness instance
    harness = Harness()

    # Define a task specification
    task_spec = TaskSpec(
        genre=[StoryGenre.PSYCHOLOGICAL_THRILLER, StoryGenre.GOTHIC],
        length_words=(2000, 2500),
        perspective=Perspective.FIRST_PERSON,
        core_tension="叙述者向读者倾诉自己策划并实施的一桩谋杀,并坚称自己神志清醒",
        key_constraints={
            "杀机来自一个具体而非理性的执念物": "身体某部位、器官、物件",
            "必须有'延宕铺垫(七夜窥伺)→ 第八夜爆发'的双段式时间结构": True,
            "杀人后必须有'看似完美的隐藏',但被一种感官信号逐渐瓦解": True,
            "结尾必须是叙述者在外人面前主动崩溃、自我招供": True
        },
        style_requirements={
            "大量破折号、感叹号、词语重复": True,
            "直接呼告读者": True,
            "以听觉意象为主导": True
        },
        raw_input="""体裁:心理惊悚 / 哥特短篇
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
    )

    # Create a new session
    session_info = harness.create_session(task_spec)
    print(f"Created session: {session_info.session_id}")

    # Run the full pipeline
    print("\nRunning full generation pipeline...")
    result = harness.run_to_completion()

    if result["success"]:
        print("\n✅ Generation completed!")
        print(f"Title: {result['result']['title']}")
        print(f"Word count: {result['result']['word_count']}")

        # Save the manuscript
        output_path = "example_story.txt"
        harness.save_manuscript(result['result']['manuscript'], output_path)
        print(f"Manuscript saved to: {output_path}")

        # Compare to sample
        print("\nComparing to sample story...")
        compare_result = harness.compare_to_sample(result['result']['manuscript'])
        print(f"Word count comparison: {compare_result['actual_word_count']} vs {compare_result['sample_word_count']}")
    else:
        print(f"\n❌ Generation failed: {result.get('error')}")

    harness.close()
    return result

def example_cli_mode():
    """Example of running in CLI mode"""
    print("\n=== CLI Mode Example ===\n")
    print("To run in CLI mode, execute:")
    print("python -m harness.cli")
    print("\nOr for single task:")
    print("python -m harness.cli \"体裁:心理惊悚短篇\n篇幅:约2000词\n视角:第一人称\" --output story.txt\n")

if __name__ == "__main__":
    # Run basic usage example
    example_basic_usage()

    # Show CLI mode info
    example_cli_mode()