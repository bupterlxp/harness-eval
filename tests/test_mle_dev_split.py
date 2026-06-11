from __future__ import annotations

import unittest

from creation_eval.mle_dev_split import (
    MLE_DEV_COMPETITIONS,
    MLE_OFFICIAL_DEV_POOL,
    competition_ids_override,
    dev_competition_ids,
    formal_competition_ids,
    is_dev_competition,
)


class MleDevSplitTests(unittest.TestCase):
    def test_dev_set_is_fixed(self) -> None:
        self.assertEqual(
            MLE_DEV_COMPETITIONS,
            ("spaceship-titanic", "ml2021spring-hw2"),
        )

    def test_dev_competitions_come_from_official_dev_pool(self) -> None:
        for competition_id in MLE_DEV_COMPETITIONS:
            self.assertIn(competition_id, MLE_OFFICIAL_DEV_POOL)

    def test_formal_set_excludes_every_official_dev_competition(self) -> None:
        all_ids = list(MLE_OFFICIAL_DEV_POOL) + ["spooky-author-identification", "leaf-classification"]
        formal = formal_competition_ids(all_ids)
        self.assertEqual(formal, ["spooky-author-identification", "leaf-classification"])
        for competition_id in dev_competition_ids():
            self.assertNotIn(competition_id, formal)
            self.assertTrue(is_dev_competition(competition_id))

    def test_override_parsing(self) -> None:
        self.assertIsNone(competition_ids_override(""))
        self.assertIsNone(competition_ids_override("   "))
        self.assertEqual(
            competition_ids_override("spaceship-titanic, ml2021spring-hw2"),
            ["spaceship-titanic", "ml2021spring-hw2"],
        )


if __name__ == "__main__":
    unittest.main()
