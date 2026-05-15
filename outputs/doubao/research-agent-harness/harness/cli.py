#!/usr/bin/env python3
"""
命令行交互界面 for 研究智能体 harness
"""

import argparse
import asyncio
import json
import os
from typing import List, Optional
from harness.core import ResearchHarness
from harness.schemas import ResearchQuery


class ResearchCLI:
    """命令行交互界面"""

    def __init__(self, output_dir: str = "./output"):
        self.harness = ResearchHarness(output_dir)
        self.current_task = None

    async def run_interactive(self):
        """启动交互式模式"""
        print("=== 研究智能体交互界面 ===")
        print("输入 'help' 查看可用命令")

        while True:
            try:
                command = input("\n>>> ").strip()
                if not command:
                    continue

                parts = command.split(maxsplit=1)
                cmd = parts[0].lower()
                args = parts[1] if len(parts) > 1 else ""

                if cmd == "help" or cmd == "?":
                    self.print_help()
                elif cmd == "exit" or cmd == "quit":
                    print("再见!")
                    break
                elif cmd == "new":
                    await self.start_new_research(args)
                elif cmd == "status":
                    self.print_status()
                elif cmd == "sources":
                    await self.list_sources()
                elif cmd == "gaps":
                    await self.show_gaps()
                elif cmd == "outline":
                    await self.show_outline()
                elif cmd == "report":
                    self.show_report()
                elif cmd == "save":
                    await self.save_state(args)
                elif cmd == "load":
                    await self.load_state(args)
                elif cmd == "run":
                    await self.run_current_task()
                else:
                    print(f"未知命令: {cmd}")

            except KeyboardInterrupt:
                print("\n操作被中断")
            except Exception as e:
                print(f"错误: {e}")

    def print_help(self):
        """显示帮助信息"""
        print("\n可用命令:")
        print("  new <topic> - 创建新的研究任务")
        print("  status - 显示当前任务状态")
        print("  sources - 列出已收集的来源")
        print("  gaps - 显示信息缺口")
        print("  outline - 显示报告大纲")
        print("  report - 显示当前报告")
        print("  run - 运行研究任务")
        print("  save <path> - 保存研究状态")
        print("  load <path> - 加载研究状态")
        print("  exit/quit - 退出程序")
        print("  help/? - 显示此帮助信息")

    async def start_new_research(self, args_str: str):
        """启动新的研究任务"""
        if not args_str:
            print("请指定研究主题")
            return

        # 尝试解析参数
        if "--questions" in args_str:
            topic, questions_part = args_str.split("--questions", 1)
            topic = topic.strip()
            questions = [q.strip() for q in questions_part.split(",") if q.strip()]
        else:
            topic = args_str
            # 使用默认的代码生成研究问题
            from harness.domain import RESEARCH_QUESTION_TEMPLATES
            default_task = RESEARCH_QUESTION_TEMPLATES["code_generation"]
            questions = default_task["questions"]
            print(f"使用默认研究问题: {len(questions)} 个问题")

        print(f"创建新研究任务: {topic}")
        self.current_task = await self.harness.create_research_task(topic, questions)
        print(f"任务创建成功! 当前状态: {self.current_task.current_state}")

    def print_status(self):
        """显示当前任务状态"""
        if not self.current_task:
            print("没有正在运行的任务")
            return

        progress = self.harness.get_current_progress()
        print(f"\n=== 当前任务状态 ===")
        print(f"主题: {progress['topic']}")
        print(f"当前状态: {progress['current_state']}")
        print(f"循环次数: {progress['loop_count']}")
        print(f"已收集来源: {progress['sources_collected']}")
        print(f"已提取证据: {progress['evidence_collected']}")
        print(f"整体进度: {progress['progress'] * 100:.1f}%")

    async def list_sources(self):
        """列出已收集的来源"""
        if not self.current_task:
            print("没有正在运行的任务")
            return

        sources = list(self.current_task.state_store.state.all_sources.values())
        print(f"\n=== 已收集的来源 ({len(sources)}) ===")

        for i, source in enumerate(sources, 1):
            reliability = source.reliability.name if hasattr(source, 'reliability') else "UNKNOWN"
            print(f"[{i}] {source.title[:60]}...")
            print(f"    URL: {source.url}")
            print(f"    可靠性: {reliability}, 相关性: {source.relevance_score:.2f}")

    async def show_gaps(self):
        """显示信息缺口"""
        if not self.current_task:
            print("没有正在运行的任务")
            return

        gaps = self.current_task.context.get_info_gaps()
        if not gaps:
            print("未发现明显的信息缺口")
            return

        print("\n=== 信息缺口 ===")
        for gap_type, gap_items in gaps.items():
            print(f"\n{gap_type}:")
            for item in gap_items:
                print(f"  - {item}")

    async def show_outline(self):
        """显示报告大纲"""
        if not self.current_task:
            print("没有正在运行的任务")
            return

        outline = self.current_task.context.outline_context.generate_full_outline()
        progress = self.current_task.context.get_overall_progress()

        print(f"\n=== 报告大纲 (进度: {progress * 100:.1f}%) ===")
        print(outline)

    def show_report(self):
        """显示当前报告"""
        if not self.current_task:
            print("没有正在运行的任务")
            return

        report = self.current_task.state_store.get_full_report()
        if not report:
            print("报告内容为空")
            return

        print("\n=== 当前报告 ===")
        print(report)

    async def save_state(self, path: str):
        """保存研究状态"""
        if not self.current_task:
            print("没有正在运行的任务")
            return

        result = await self.harness.save_state(path)
        print(result)

    async def load_state(self, path: str):
        """加载研究状态"""
        # TODO: 实现加载状态
        print("加载功能尚未实现")

    async def run_current_task(self):
        """运行当前任务"""
        if not self.current_task:
            print("没有正在运行的任务")
            print("请先使用 'new' 命令创建任务")
            return

        print("开始运行研究任务...")
        print("按 Ctrl+C 中断")
        try:
            await self.current_task.run()
            print("研究任务完成!")
        except Exception as e:
            print(f"任务运行出错: {e}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="研究智能体命令行工具")
    parser.add_argument("--output-dir", default="./output", help="输出目录")
    parser.add_argument("--interactive", "-i", action="store_true", help="交互式模式")
    parser.add_argument("--topic", "-t", help="研究主题")
    parser.add_argument("--questions", "-q", nargs="+", help="研究问题列表")
    parser.add_argument("--sample", action="store_true", help="使用示例研究任务")

    args = parser.parse_args()

    cli = ResearchCLI(args.output_dir)

    if args.sample:
        # 加载示例研究任务
        from harness.domain import RESEARCH_QUESTION_TEMPLATES
        task_data = RESEARCH_QUESTION_TEMPLATES["code_generation"]
        asyncio.run(cli.harness.run_research_task(
            topic=task_data["topic"],
            questions=task_data["questions"]
        ))
        return

    if args.interactive:
        asyncio.run(cli.run_interactive())
    elif args.topic:
        questions = args.questions or []
        asyncio.run(cli.harness.run_research_task(args.topic, questions))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()