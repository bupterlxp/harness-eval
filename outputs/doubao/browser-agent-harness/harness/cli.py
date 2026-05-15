import os
import json
from typing import Dict, Optional
from datetime import datetime

from .schemas import Config
from .execution import ExecutionEngine


class BrowserAgent:
    """Main browser agent harness class"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = self._load_config(config)
        self.engine = ExecutionEngine(self.config)

    def _load_config(self, custom_config: Optional[Dict] = None) -> Dict:
        """Load configuration with defaults"""
        default_config = {
            "base_url": "http://localhost:5000",
            "default_timeout": 30000,
            "max_retries": 3,
            "viewport_width": 1280,
            "viewport_height": 720,
            "screenshot_dir": "screenshots",
            "download_dir": "downloads",
            "report_dir": "reports",
            "evaluation_dir": "evaluation"
        }

        if custom_config:
            default_config.update(custom_config)

        return default_config

    def run_from_scenario(self, scenario_file: str) -> Dict[str, Any]:
        """Run task from scenario JSON file"""
        with open(scenario_file, "r", encoding="utf-8") as f:
            scenario_data = json.load(f)

        scenario = scenario_data.get("scenario", {})
        steps = scenario.get("steps", [])

        print(f"Starting task: {scenario.get('name', 'Unnamed Task')}")
        print(f"Description: {scenario.get('description', '')}")
        print(f"Found {len(steps)} steps in scenario")

        # Launch browser first
        self.engine.tools.launch_browser()

        # Run the task sequence
        results = self.engine.run_task_sequence(steps)

        return results

    def run_demo(self) -> Dict[str, Any]:
        """Run the demo HR management scenario"""
        scenario_path = os.path.join(os.path.dirname(__file__), "..", "samples", "task_scenarios.json")
        return self.run_from_scenario(scenario_path)

    def get_status(self) -> Dict[str, Any]:
        """Get current agent status"""
        if self.engine.context.task_context:
            return self.engine.context.get_current_status()
        return {"status": "no_active_task"}

    def take_screenshot(self, custom_path: Optional[str] = None) -> Optional[str]:
        """Take a screenshot immediately"""
        if not self.engine.tools.page:
            return None

        if not custom_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            custom_path = os.path.join(
                self.config["screenshot_dir"],
                f"manual_screenshot_{timestamp}.png"
            )

        return self.engine.tools.screenshot(custom_path)


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Browser Agent Harness for Web Automation")
    parser.add_argument("--scenario", type=str, help="Path to scenario JSON file")
    parser.add_argument("--base-url", type=str, default="http://localhost:5000", help="Base URL of the target system")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--demo", action="store_true", help="Run the demo HR scenario")

    args = parser.parse_args()

    config = {}
    if args.base_url:
        config["base_url"] = args.base_url
    if args.headless:
        # Note: headless mode is handled in the browser launch
        pass

    agent = BrowserAgent(config)

    if args.demo:
        print("Running demo HR management scenario...")
        results = agent.run_demo()
    elif args.scenario:
        print(f"Running scenario from {args.scenario}...")
        results = agent.run_from_scenario(args.scenario)
    else:
        parser.print_help()
        return

    # Print summary
    print("\n" + "="*60)
    print("TASK COMPLETION SUMMARY")
    print("="*60)
    print(f"Success rate: {results['summary']['success_rate']:.1f}%")
    print(f"Completed steps: {results['summary']['completed_steps']}/{results['summary']['total_steps']}")
    print(f"Failed steps: {results['summary']['failed_steps']}")
    print(f"Total duration: {results['summary']['duration']:.2f} seconds")
    print(f"Screenshots taken: {results['summary']['screenshots_taken']}")
    print(f"Total retries: {results['summary']['total_retries']}")
    print("="*60 + "\n")

    print(f"Full report saved to: {results['summary'].get('report_file', 'N/A')}")
    print(f"Trajectory data saved to: {results['trajectory_file']}")
    print(f"Context data saved to: {results['context_file']}")


if __name__ == "__main__":
    main()