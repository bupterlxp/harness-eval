import pytest
import json
import os
from unittest.mock import patch, MagicMock
from harness.execution import ExecutionEngine
from harness.schemas import TaskStatus


def test_full_e2e_scenario():
    """End-to-end test of the complete 12-step HR scenario"""
    # Load the test scenario
    scenario_path = os.path.join(os.path.dirname(__file__), "..", "samples", "task_scenarios.json")
    with open(scenario_path, "r", encoding="utf-8") as f:
        scenario_data = json.load(f)

    scenario = scenario_data["scenario"]
    steps = scenario["steps"]

    config = {
        "base_url": "http://localhost:5000",
        "max_retries": 2,
        "screenshot_dir": "test_screenshots"
    }

    engine = ExecutionEngine(config)
    engine.start_task("e2e_test")

    # Mock all browser operations
    with patch.object(engine.tools, 'launch_browser'):
        with patch.object(engine.tools, 'close_browser'):
            # Mock navigate
            with patch.object(engine.tools, 'navigate') as mock_navigate:
                mock_navigate.return_value.status = TaskStatus.COMPLETED

                # Mock wait_for_load
                with patch.object(engine.tools, 'wait_for_load', return_value=True):
                    # Mock wait_for_element
                    with patch.object(engine.tools, 'wait_for_element', return_value=True):
                        # Mock fill
                        with patch.object(engine.tools, 'fill'):
                            # Mock click
                            with patch.object(engine.tools, 'click') as mock_click:
                                # Mock select
                                with patch.object(engine.tools, 'select'):
                                    # Mock extract_text
                                    with patch.object(engine.tools, 'extract_text') as mock_extract:
                                        mock_extract.side_effect = [
                                            "50",  # total employees
                                            "8",   # pending leaves
                                            "3",   # new hires
                                            "5",   # contract expiring
                                            "5",   # search result count
                                            "张伟", # first employee name
                                            "张伟", # employee name
                                            "技术部", # department
                                            "高级工程师", # position
                                            "2021-03-15", # hire date
                                            "8.5", # leave balance
                                            "85.2", # performance score
                                            "95.5" # attendance rate
                                        ]

                                        # Mock download_file
                                        with patch.object(engine.tools, 'download_file', return_value="/tmp/test.csv"):
                                            # Mock screenshot
                                            with patch.object(engine.tools, 'screenshot', return_value="/tmp/screenshot.png"):
                                                # Run the scenario
                                                report = engine.run_task_sequence(steps)

                                                # Verify all steps completed
                                                assert report["summary"]["total_steps"] == 12
                                                assert report["summary"]["completed_steps"] == 12
                                                assert report["summary"]["success_rate"] == 100.0

                                                # Verify data was extracted
                                                extracted_data = engine.context.get_extracted_data()
                                                assert "dashboard" in extracted_data
                                                assert "employees_search" in extracted_data
                                                assert "employee_detail" in extracted_data
                                                assert "attendance" in extracted_data

                                                assert extracted_data["dashboard"]["total_employees"] == 50
                                                assert extracted_data["dashboard"]["pending_leaves"] == 8
                                                assert extracted_data["employees_search"]["first_employee_name"] == "张伟"
                                                assert extracted_data["employee_detail"]["name"] == "张伟"


if __name__ == "__main__":
    test_full_e2e_scenario()