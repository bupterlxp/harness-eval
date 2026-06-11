"""Fixed MLE-bench dev/formal competition split for harness experiments.

Dev competitions are used by creation-time self-tests (``run_dev_bmk.py``).
They were drawn once with a fixed seed so every generation model sees the
same dev set:

    pool = sorted(official experiments/splits/dev.txt, locally registered)
    random.Random(20260610).sample(pool, 3)

The official MLE-bench dev split (``experiments/splits/dev.txt``) is disjoint
from the official 75-competition formal split (``experiments/splits/split75.txt``),
so excluding every official dev competition from "all competitions" leaves
exactly the official formal set. Do not edit the drawn ids; changing them
breaks comparability across generation models.

2026-06-12: ``playground-series-s3e18`` was dropped from the drawn set. The
Kaggle competition has expired, its rules can no longer be accepted, so its
data can never be prepared; every harness saw it only as
``skipped/missing_dependency``. The two remaining competitions stay exactly
as drawn and remain identical for every generation model.
"""
from __future__ import annotations

import os

MLE_DEV_SPLIT_SEED = 20260610

# Seeded draw result minus the expired playground-series-s3e18 (see module
# docstring). Identical for every generation model.
MLE_DEV_COMPETITIONS: tuple[str, ...] = (
    "spaceship-titanic",
    "ml2021spring-hw2",
)

# Full official dev pool (experiments/splits/dev.txt). All of these are
# excluded from formal eval so the formal set equals the official split75.
MLE_OFFICIAL_DEV_POOL: tuple[str, ...] = (
    "invasive-species-monitoring",
    "ml2021spring-hw2",
    "movie-review-sentiment-analysis-kernels-only",
    "paddy-disease-classification",
    "plant-seedlings-classification",
    "playground-series-s3e18",
    "spaceship-titanic",
)

COMPETITION_IDS_ENV = "MLEBENCH_COMPETITION_IDS"


def dev_competition_ids() -> list[str]:
    return list(MLE_DEV_COMPETITIONS)


def is_dev_competition(competition_id: str) -> bool:
    return str(competition_id) in MLE_OFFICIAL_DEV_POOL


def competition_ids_override(env_value: str | None = None) -> list[str] | None:
    """Parse an explicit competition-id list from the environment.

    ``MLEBENCH_COMPETITION_IDS=a,b,c`` restricts an ``competition_id: all``
    MLE run to exactly those competitions (dev runs use this). Returns None
    when the variable is unset or empty.
    """
    raw = env_value if env_value is not None else os.environ.get(COMPETITION_IDS_ENV)
    if not raw or not str(raw).strip():
        return None
    ids = [item.strip() for item in str(raw).split(",") if item.strip()]
    return ids or None


def formal_competition_ids(all_ids: list[str]) -> list[str]:
    """Drop every official dev competition from a registry listing.

    With the full 82-competition local registry this yields the official
    75-competition MLE-bench formal split.
    """
    dev = set(MLE_OFFICIAL_DEV_POOL)
    return [competition_id for competition_id in all_ids if str(competition_id) not in dev]
