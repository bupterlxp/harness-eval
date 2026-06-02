from __future__ import annotations

import argparse
import unittest

from run_self_evolve import annotate_round_metrics, limit_tasks_per_harness, resolve_goal


class SelfEvolveUtilityTests(unittest.TestCase):
    def test_limits_tasks_per_harness(self) -> None:
        tasks = [
            {"harness": "openhands", "instruction": "a"},
            {"harness": "openhands", "instruction": "b"},
            {"harness": "opencode", "instruction": "c"},
            {"repo": "fallback-repo", "instruction": "d"},
            {"instruction": "e"},
        ]

        selected, summary = limit_tasks_per_harness(tasks, 1)

        self.assertEqual([task["instruction"] for task in selected], ["a", "c", "d", "e"])
        self.assertEqual(summary["counts"]["openhands"], 1)
        self.assertEqual(summary["counts"]["opencode"], 1)
        self.assertEqual(summary["counts"]["fallback-repo"], 1)
        self.assertEqual(summary["counts"]["unknown"], 1)
        self.assertEqual(summary["skipped"], 1)
        self.assertTrue(summary["warnings"])

    def test_goal_override_precedes_preset(self) -> None:
        args = argparse.Namespace(goal="custom goal", goal_preset="mle_bench", eval_bench="mle_bench")

        self.assertEqual(resolve_goal(args, "data_analysis"), "custom goal")

    def test_goal_preset_is_high_level(self) -> None:
        args = argparse.Namespace(goal=None, goal_preset="terminal_2_bench", eval_bench="terminal_2_bench")
        goal = resolve_goal(args, "code")

        self.assertIn("Terminal 2.0", goal)
        self.assertNotIn("90", goal)
        self.assertNotIn("hidden score", goal.lower())

    def test_plateau_uses_best_score_stagnation(self) -> None:
        rows = [
            {"round": 0, "avg_score": 1.0},
            {"round": 1, "avg_score": 2.0},
            {"round": 2, "avg_score": 2.0},
            {"round": 3, "avg_score": 2.0},
        ]

        summary = annotate_round_metrics(rows, plateau_patience=2, plateau_min_delta=1e-6)

        self.assertEqual(summary["best_score"], 2.0)
        self.assertEqual(summary["best_round"], 1)
        self.assertEqual(summary["round_to_plateau"], 2)
        self.assertEqual(rows[-1]["round_to_plateau"], 2)
        self.assertEqual(rows[-1]["best_score_so_far"], 2.0)


if __name__ == "__main__":
    unittest.main()
