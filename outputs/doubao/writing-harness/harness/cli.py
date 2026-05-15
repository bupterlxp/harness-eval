#!/usr/bin/env python3
"""CLI interface for the short story generation harness"""

import argparse
import sys
import os
import json
import readline
from typing import Optional, List, Dict, Any
from uuid import UUID
from .core import Harness
from .schemas import TaskSpec, StoryGenre, Perspective
from .domain.tools import (
    GenerateNarratorProfileTool,
    GeneratePlotOutlineTool,
    GenerateSceneOutlineTool,
    DraftSceneTool,
    CheckConsistencyTool,
    ReviseStyleTool,
    AssembleFinalManuscriptTool,
    CompareToSampleTool
)
from .lifecycle import ApprovalRequest, ApprovalResponse


class CLI:
    """CLI interface for the story generation harness"""

    def __init__(self):
        self.harness = Harness()
        self._register_tools()
        self._setup_approval_handler()
        self.session_id: Optional[UUID] = None
        self.current_approval_request: Optional[ApprovalRequest] = None

    def _register_tools(self):
        """Register all domain-specific tools"""
        tools = [
            GenerateNarratorProfileTool(),
            GeneratePlotOutlineTool(),
            GenerateSceneOutlineTool(),
            DraftSceneTool(),
            CheckConsistencyTool(),
            ReviseStyleTool(),
            AssembleFinalManuscriptTool(),
            CompareToSampleTool()
        ]

        for tool in tools:
            self.harness.register_tool(tool)

    def _setup_approval_handler(self):
        """Setup approval handler for user confirmation"""
        def approval_callback(request: ApprovalRequest) -> ApprovalResponse:
            self.current_approval_request = request
            print(f"\n⚠️  Approval required for tool: {request.tool_name}")
            print(f"Description: {request.description}")
            print(f"Risk level: {request.risk_level}")
            print(f"Parameters: {json.dumps(request.parameters, indent=2, ensure_ascii=False)}")

            while True:
                response = input("\nApprove? (y/n/edit): ").lower().strip()
                if response in ['y', 'yes']:
                    return ApprovalResponse(approved=True)
                elif response in ['n', 'no']:
                    return ApprovalResponse(approved=False)
                elif response in ['e', 'edit']:
                    print("Editing parameters...")
                    new_params = input("Enter new parameters JSON: ")
                    try:
                        modified = json.loads(new_params)
                        return ApprovalResponse(
                            approved=True,
                            modified_parameters=modified
                        )
                    except json.JSONDecodeError:
                        print("Invalid JSON, please try again")
                else:
                    print("Please enter y, n, or e")

        from .lifecycle import ApprovalHookHandler
        self.harness.hook_manager.register_handler(ApprovalHookHandler(approval_callback))

    def parse_task_spec(self, raw_input: str) -> TaskSpec:
        """Parse raw task input into TaskSpec object"""
        # Simple parser - in production would use more robust parsing
        spec_data = {
            "raw_input": raw_input,
            "genre": [StoryGenre.PSYCHOLOGICAL_THRILLER],
            "length_words": (2000, 2500),
            "perspective": Perspective.FIRST_PERSON,
            "core_tension": "",
            "key_constraints": {},
            "style_requirements": {}
        }

        lines = raw_input.split('\n')
        current_section = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip().lower()
                value = value.strip()

                if '体裁' in key or 'genre' in key:
                    genres = [g.strip() for g in value.split('/')]
                    spec_data['genre'] = []
                    for g in genres:
                        if '心理惊悚' in g or 'psychological thriller' in g:
                            spec_data['genre'].append(StoryGenre.PSYCHOLOGICAL_THRILLER)
                        elif '哥特' in g or 'gothic' in g:
                            spec_data['genre'].append(StoryGenre.GOTHIC)
                        elif '恐怖' in g or 'horror' in g:
                            spec_data['genre'].append(StoryGenre.HORROR)
                elif '篇幅' in key or 'length' in key:
                    if '–' in value or '-' in value:
                        parts = value.replace('–', '-').split('-')
                        spec_data['length_words'] = (int(parts[0].strip()), int(parts[1].strip()))
                elif '视角' in key or 'perspective' in key:
                    if '第一人称' in value or 'first person' in value:
                        spec_data['perspective'] = Perspective.FIRST_PERSON
                elif '核心张力' in key or 'core_tension' in key:
                    spec_data['core_tension'] = value
                elif '关键约束' in key or 'key_constraints' in key:
                    current_section = 'key_constraints'
                elif '风格要求' in key or 'style_requirements' in key:
                    current_section = 'style_requirements'
            elif line.startswith('-') and current_section:
                line = line.lstrip('- ').strip()
                if ':' in line:
                    key, value = line.split(':', 1)
                    spec_data[current_section][key.strip()] = value.strip()
                else:
                    spec_data[current_section][line] = True

        return TaskSpec(**spec_data)

    def run_single_task(self, task_input: str, output_file: str = "output_story.txt"):
        """Run single task from command line"""
        print("📝 Parsing task specification...")
        task_spec = self.parse_task_spec(task_input)

        print("🚀 Creating new session...")
        session_info = self.harness.create_session(task_spec)
        self.session_id = session_info.session_id

        print(f"✅ Session created with ID: {self.session_id}")

        print("🏃‍♂️ Running generation pipeline...")
        result = self.harness.run_to_completion()

        if result.get('success'):
            print("✅ Generation completed successfully!")
            manuscript = result['result']['manuscript']
            title = result['result']['title']

            print(f"\n📖 Story Title: {title}")
            print(f"📏 Word count: {result['result']['word_count']}")

            if output_file:
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(manuscript)
                print(f"💾 Story saved to: {output_file}")

            # Run comparison
            print("🔍 Comparing to sample story...")
            compare_result = self.harness.compare_to_sample(manuscript)
            print(f"📊 Comparison results:")
            print(f"   Sample word count: {compare_result['sample_word_count']}")
            print(f"   Actual word count: {compare_result['actual_word_count']}")
            print(f"   Difference: {compare_result['word_count_difference']}")

        else:
            print(f"❌ Generation failed: {result.get('error', 'Unknown error')}")

        self.harness.close()
        return result

    def run_repl(self):
        """Run interactive REPL mode"""
        print("🤖 Short Story Generation Harness")
        print("Type 'help' for available commands, 'exit' to quit")

        while True:
            try:
                prompt = input("\n>>> ")
                if not prompt:
                    continue

                command = prompt.strip().lower()

                if command in ['exit', 'quit']:
                    print("👋 Goodbye!")
                    break

                elif command in ['help', '?']:
                    self._print_help()

                elif command == 'clear':
                    if self.session_id:
                        print(f"🧹 Clearing context for session {self.session_id}")
                        self.harness.context_manager.clear()

                elif command.startswith('/resume'):
                    parts = command.split()
                    if len(parts) > 1:
                        try:
                            session_id = UUID(parts[1])
                            print(f"🔄 Resuming session {session_id}")
                            session_info = self.harness.load_session(session_id)
                            if session_info:
                                self.session_id = session_id
                                print(f"✅ Resumed session: {session_id}")
                            else:
                                print(f"❌ Session not found: {session_id}")
                        except ValueError:
                            print(f"❌ Invalid session ID: {parts[1]}")

                elif command == '/trajectory':
                    if self.session_id:
                        trajectory = self.harness.trajectory_recorder.get_full_trajectory(self.session_id)
                        print(f"📋 Trajectory entries: {len(trajectory)}")
                        for entry in trajectory:
                            print(f"  - {entry['state']}: {entry['step_description']}")

                elif command == '/diff':
                    if self.session_id:
                        # Get latest manuscript
                        if hasattr(self.harness, 'current_execution_loop') and self.harness.current_execution_loop:
                            # This is simplified - would need actual manuscript storage
                            print("🔍 Diff comparison not fully implemented yet")
                            # In real implementation would compare current manuscript to sample

                elif command.startswith('/'):
                    print(f"❌ Unknown command: {command}")

                else:
                    # Assume this is a task input
                    if not self.session_id:
                        print("🚀 Creating new session...")
                        task_spec = self.parse_task_spec(prompt)
                        session_info = self.harness.create_session(task_spec)
                        self.session_id = session_info.session_id
                        print(f"✅ Session created with ID: {self.session_id}")

                    print("🏃‍♂️ Running generation step...")
                    result = self.harness.run_step()

                    if result.get('waiting'):
                        print(f"⏳ Waiting for user input...")
                        if self.current_approval_request:
                            # Approval already handled in callback
                            pass

                    elif result.get('success'):
                        print("✅ Step completed successfully!")
                        if 'result_data' in result and 'manuscript' in result['result_data']:
                            manuscript = result['result_data']['manuscript']
                            print(f"\n📖 Final Manuscript:\n{manuscript}")

                    else:
                        print(f"❌ Step failed: {result.get('error', 'Unknown error')}")
                        print(f"Current state: {result.get('current_state')}")

            except KeyboardInterrupt:
                print("\n👋 Exiting...")
                break
            except EOFError:
                print("\n👋 Exiting...")
                break
            except Exception as e:
                print(f"❌ Error: {str(e)}")

        self.harness.close()

    def _print_help(self):
        """Print help message"""
        print("\nAvailable commands:")
        print("  help, ?          - Show this help message")
        print("  exit, quit       - Exit the program")
        print("  clear            - Clear current context")
        print("  /resume <id>     - Resume a previous session")
        print("  /trajectory      - Show generation trajectory")
        print("  /diff            - Compare current story to sample")
        print("\nJust type a task description to generate a story!")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Short Story Generation Harness")
    parser.add_argument('task', nargs='?', help="Task specification for story generation")
    parser.add_argument('--output', '-o', default="output_story.txt", help="Output file path")
    parser.add_argument('--repl', '-r', action='store_true', help="Run in interactive REPL mode")

    args = parser.parse_args()

    cli = CLI()

    if args.repl:
        cli.run_repl()
    elif args.task:
        cli.run_single_task(args.task, args.output)
    else:
        # Default to REPL mode
        cli.run_repl()


if __name__ == "__main__":
    main()