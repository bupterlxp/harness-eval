"""Scaffold-native generated data-analysis harness program."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Optional

from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.schemas import HarnessResult
from harness_scaffold.examples._common import make_result, try_tool
from harness_scaffold.tools.registry import ToolRegistry


ANALYSIS_SCRIPT = r'''
from __future__ import annotations

import csv
import json
import math
import os
import re
import sqlite3
import statistics
import sys
import traceback
from collections import Counter, defaultdict
from pathlib import Path

try:
    import numpy as np
except Exception:
    np = None
try:
    import pandas as pd
except Exception:
    pd = None
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except Exception:
    plt = None


def safe_json(value):
    if pd is not None:
        try:
            if pd.isna(value):
                return None
        except Exception:
            pass
    if np is not None:
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, np.ndarray):
            return value.tolist()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
    if isinstance(value, dict):
        return {str(k): safe_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_json(v) for v in value]
    return value


def write_json(path, obj):
    path.write_text(json.dumps(safe_json(obj), ensure_ascii=False, indent=2), encoding="utf-8")


def norm_name(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def discover_files(workdir):
    patterns = [
        "*.csv", "*.tsv", "*.json", "*.jsonl", "*.parquet", "*.pq", "*.xlsx", "*.xls",
        "*.sqlite", "*.db", "train*", "test*", "sample_submission*", "README*", "readme*",
        "instructions*", "Instructions*", "*.txt", "*.md",
    ]
    found = {}
    ignored = {".git", "node_modules", "__pycache__", ".venv", "venv", "dev_bmk_runs"}
    for pattern in patterns:
        for path in workdir.rglob(pattern):
            if not path.is_file():
                continue
            if any(part in ignored for part in path.relative_to(workdir).parts):
                continue
            found[str(path.relative_to(workdir))] = path
    return [found[k] for k in sorted(found)]


def read_text_limited(path, limit=12000):
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def read_table(path, nrows=None):
    if pd is None:
        return read_table_stdlib(path, nrows=nrows)
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv" or suffix == "":
            return pd.read_csv(path, nrows=nrows, low_memory=False)
        if suffix == ".tsv":
            return pd.read_csv(path, sep="\t", nrows=nrows, low_memory=False)
        if suffix in {".xlsx", ".xls"}:
            return pd.read_excel(path, nrows=nrows)
        if suffix in {".parquet", ".pq"}:
            return pd.read_parquet(path)
        if suffix == ".json":
            try:
                return pd.read_json(path, lines=False)
            except ValueError:
                return pd.read_json(path, lines=True)
        if suffix == ".jsonl":
            return pd.read_json(path, lines=True)
    except Exception:
        if suffix in {".csv", ".tsv"}:
            for enc in ("latin1", "cp1252"):
                try:
                    return pd.read_csv(path, sep="\t" if suffix == ".tsv" else ",", encoding=enc, nrows=nrows, low_memory=False)
                except Exception:
                    pass
        raise
    return None


def read_table_stdlib(path, nrows=None):
    suffix = path.suffix.lower()
    if suffix not in {".csv", ".tsv"}:
        return None
    sep = "\t" if suffix == ".tsv" else ","
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        rows = list(csv.DictReader(handle, delimiter=sep))
    if nrows is not None:
        rows = rows[:nrows]
    if pd is not None:
        return pd.DataFrame(rows)
    return rows


def table_shape(df):
    if pd is not None and hasattr(df, "shape"):
        return [int(df.shape[0]), int(df.shape[1])]
    if isinstance(df, list):
        cols = len(df[0]) if df else 0
        return [len(df), cols]
    return [0, 0]


def dataframe_columns(df):
    if pd is not None and hasattr(df, "columns"):
        return [str(c) for c in df.columns]
    if isinstance(df, list) and df:
        return list(df[0].keys())
    return []


def compact_summary(path, df):
    shape = table_shape(df)
    cols = dataframe_columns(df)
    summary = {"path": str(path), "rows": shape[0], "columns": shape[1], "column_names": cols[:80]}
    if pd is not None and hasattr(df, "dtypes"):
        summary["dtypes"] = {str(k): str(v) for k, v in df.dtypes.items()}
        missing = df.isna().sum().sort_values(ascending=False).head(30)
        summary["missing_top"] = {str(k): int(v) for k, v in missing.items()}
        numeric = df.select_dtypes(include="number")
        if numeric.shape[1]:
            desc = numeric.describe().T.head(30)
            summary["numeric_describe"] = desc.round(6).to_dict(orient="index")
        cats = []
        for c in df.columns[:80]:
            s = df[c]
            if not pd.api.types.is_numeric_dtype(s) or s.nunique(dropna=True) <= 20:
                vc = s.astype(str).value_counts(dropna=False).head(8).to_dict()
                cats.append({"column": str(c), "unique": int(s.nunique(dropna=True)), "top_values": {str(k): int(v) for k, v in vc.items()}})
        summary["categorical_samples"] = cats[:20]
    else:
        summary["sample_rows"] = df[:5] if isinstance(df, list) else []
    return summary


def find_first(files, names):
    for path in files:
        low = path.name.lower()
        if any(name in low for name in names):
            return path
    return None


def candidate_tables(files):
    supported = {".csv", ".tsv", ".json", ".jsonl", ".parquet", ".pq", ".xlsx", ".xls"}
    return [p for p in files if p.suffix.lower() in supported or p.name.lower().startswith(("train", "test", "sample_submission"))]


def load_sqlite_metrics(path):
    metrics = []
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        tables = [r[0] for r in cur.execute("select name from sqlite_master where type='table'").fetchall()]
        for table in tables[:20]:
            count = cur.execute(f"select count(*) from [{table}]").fetchone()[0]
            cols = [r[1] for r in cur.execute(f"pragma table_info([{table}])").fetchall()]
            metrics.append({"database": path.name, "table": table, "rows": count, "columns": cols})
        conn.close()
    except Exception as exc:
        metrics.append({"database": path.name, "error": str(exc)})
    return metrics


def infer_id_columns(sample_df, test_df):
    sample_cols = dataframe_columns(sample_df)
    if not sample_cols:
        return []
    if len(sample_cols) == 1:
        return []
    test_cols = set(dataframe_columns(test_df)) if test_df is not None else set()
    ids = []
    for col in sample_cols:
        low = norm_name(col)
        if col in test_cols or low in {"id", "row_id", "index", "key", "customer_id", "entity_id"} or low.endswith("_id"):
            ids.append(col)
        else:
            break
    return ids or [sample_cols[0]]


def infer_target_columns(sample_df, test_df):
    cols = dataframe_columns(sample_df)
    id_cols = infer_id_columns(sample_df, test_df)
    targets = [c for c in cols if c not in id_cols]
    return targets or cols[1:] or cols


def choose_train_target(train_df, sample_targets, test_df):
    if train_df is None or pd is None or not hasattr(train_df, "columns"):
        return None
    train_cols = list(train_df.columns)
    test_cols = set(test_df.columns) if test_df is not None and hasattr(test_df, "columns") else set()
    for target in sample_targets:
        if target in train_cols and target not in test_cols:
            return target
    norm_targets = {norm_name(t): t for t in sample_targets}
    for col in train_cols:
        if norm_name(col) in norm_targets and col not in test_cols:
            return col
    preferred = ["target", "label", "class", "y", "outcome", "price", "score", "rating", "is_fraud", "churn", "Survived"]
    for pref in preferred:
        for col in train_cols:
            if norm_name(col) == norm_name(pref) and col not in test_cols:
                return col
    non_test = [c for c in train_cols if c not in test_cols]
    non_id = [c for c in non_test if norm_name(c) not in {"id", "row_id", "index"} and not norm_name(c).endswith("_id")]
    return non_id[-1] if non_id else (train_cols[-1] if train_cols else None)


def sample_value_kind(series):
    vals = [str(v).strip() for v in list(series.dropna().unique()[:20])] if pd is not None and hasattr(series, "dropna") else []
    low = {v.lower() for v in vals if v != ""}
    if low and low.issubset({"true", "false"}):
        return "bool"
    if low and low.issubset({"0", "1", "0.0", "1.0"}):
        return "binary_numeric"
    return "generic"


def coerce_to_sample_domain(pred, sample_series, train_target_series=None):
    if pd is None:
        return pred
    out = pd.Series(pred).reset_index(drop=True)
    kind = sample_value_kind(sample_series)
    sample_nonempty = sample_series.dropna() if hasattr(sample_series, "dropna") else sample_series
    if kind == "bool":
        if out.dtype.kind in "fc":
            out = out >= 0.5
        out = out.map(lambda x: "True" if str(x).strip().lower() in {"true", "1", "1.0", "yes"} or x is True else "False")
        return out
    if kind == "binary_numeric":
        if out.dtype.kind in "fc":
            out = (out >= 0.5).astype(int)
        return out.astype(int)
    if train_target_series is not None:
        nonnull = train_target_series.dropna()
        if len(nonnull):
            if pd.api.types.is_integer_dtype(nonnull):
                return pd.to_numeric(out, errors="coerce").round().fillna(int(nonnull.median())).astype(int)
            if not pd.api.types.is_numeric_dtype(nonnull):
                allowed = set(str(x) for x in nonnull.unique()[:1000])
                mode = str(nonnull.mode().iloc[0]) if len(nonnull.mode()) else str(nonnull.iloc[0])
                return out.map(lambda x: str(x) if str(x) in allowed else mode)
    if len(sample_nonempty) and pd.api.types.is_integer_dtype(sample_nonempty):
        return pd.to_numeric(out, errors="coerce").round().fillna(0).astype(int)
    return out


def prepare_features(train_df, test_df, target_col):
    if pd is None:
        return None
    train = train_df.copy()
    test = test_df.copy() if test_df is not None else None
    feature_cols = [c for c in train.columns if c != target_col]
    if test is not None:
        feature_cols = [c for c in feature_cols if c in test.columns]
    feature_cols = [c for c in feature_cols if train[c].nunique(dropna=True) > 1]
    if not feature_cols:
        return None
    X_all = train[feature_cols]
    if test is not None:
        X_all = pd.concat([X_all, test[feature_cols]], axis=0, ignore_index=True)
    for c in X_all.columns:
        if pd.api.types.is_datetime64_any_dtype(X_all[c]):
            X_all[c] = pd.to_datetime(X_all[c], errors="coerce").astype("int64") // 10**9
        elif X_all[c].dtype == object:
            sample = X_all[c].dropna().astype(str).head(100)
            parsed = pd.to_datetime(sample, errors="coerce") if len(sample) else pd.Series([], dtype="datetime64[ns]")
            if len(sample) and parsed.notna().mean() > 0.8:
                X_all[c] = pd.to_datetime(X_all[c], errors="coerce").astype("int64") // 10**9
    X_all = pd.get_dummies(X_all, dummy_na=True)
    X_all = X_all.replace([float("inf"), float("-inf")], None)
    X_all = X_all.fillna(X_all.median(numeric_only=True)).fillna(0)
    X_train = X_all.iloc[:len(train)].copy()
    X_test = X_all.iloc[len(train):].copy() if test is not None else None
    return X_train, X_test, feature_cols


def baseline_values(train_df, target_col, n, sample_series=None):
    if pd is None or train_df is None or target_col not in train_df.columns:
        default = 0
        if sample_series is not None and hasattr(sample_series, "dropna") and len(sample_series.dropna()):
            default = sample_series.dropna().iloc[0]
        return [default] * n, "sample/default constant baseline"
    y = train_df[target_col].dropna()
    if not len(y):
        return [0] * n, "empty-target zero baseline"
    if pd.api.types.is_numeric_dtype(y) and y.nunique(dropna=True) > 12:
        val = float(y.median())
        return [val] * n, f"median baseline from training target {target_col}"
    mode = y.mode(dropna=True)
    val = mode.iloc[0] if len(mode) else y.iloc[0]
    return [val] * n, f"majority/mode baseline from training target {target_col}"


def train_predict(train_df, test_df, target_col, sample_df, target_col_out):
    n = len(sample_df) if hasattr(sample_df, "__len__") else 0
    if pd is None or train_df is None or test_df is None or target_col is None:
        return baseline_values(train_df, target_col, n, sample_df[target_col_out] if target_col_out in sample_df else None)
    y = train_df[target_col]
    nonnull = y.notna()
    if nonnull.sum() < 3:
        return baseline_values(train_df, target_col, n, sample_df[target_col_out] if target_col_out in sample_df else None)
    prepared = prepare_features(train_df.loc[nonnull].copy(), test_df.copy(), target_col)
    if prepared is None:
        return baseline_values(train_df, target_col, n, sample_df[target_col_out] if target_col_out in sample_df else None)
    X_train, X_test, feature_cols = prepared
    if X_test is None or len(X_test) == 0:
        return baseline_values(train_df, target_col, n, sample_df[target_col_out] if target_col_out in sample_df else None)
    y_train = y.loc[nonnull]
    try:
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor, ExtraTreesClassifier, ExtraTreesRegressor
        from sklearn.linear_model import LogisticRegression, Ridge
        from sklearn.model_selection import train_test_split
        is_reg = pd.api.types.is_numeric_dtype(y_train) and y_train.nunique(dropna=True) > max(12, min(100, len(y_train) // 20))
        model_name = ""
        validation = {}
        if is_reg:
            model = ExtraTreesRegressor(n_estimators=120, random_state=1, min_samples_leaf=2, n_jobs=-1)
            fallback = Ridge()
        else:
            model = ExtraTreesClassifier(n_estimators=160, random_state=1, min_samples_leaf=2, n_jobs=-1)
            fallback = LogisticRegression(max_iter=500)
        if len(y_train) >= 30 and y_train.nunique(dropna=True) > 1:
            try:
                X_tr, X_va, y_tr, y_va = train_test_split(X_train, y_train, test_size=0.2, random_state=2, stratify=None if is_reg else y_train)
                model.fit(X_tr, y_tr)
                pred_va = model.predict(X_va)
                if is_reg:
                    mae = float(np.mean(np.abs(np.asarray(pred_va, dtype=float) - np.asarray(y_va, dtype=float)))) if np is not None else None
                    validation = {"metric": "mae", "value": mae, "rows": int(len(y_va))}
                else:
                    acc = float((pd.Series(pred_va).reset_index(drop=True).astype(str) == y_va.reset_index(drop=True).astype(str)).mean())
                    validation = {"metric": "accuracy", "value": acc, "rows": int(len(y_va))}
            except Exception:
                validation = {"metric": "not_available", "value": None}
        try:
            model.fit(X_train, y_train)
            pred = model.predict(X_test)
            model_name = type(model).__name__
        except Exception:
            fallback.fit(X_train, y_train)
            pred = fallback.predict(X_test)
            model_name = type(fallback).__name__
        if len(pred) != n:
            pred = list(pred)[:n] + list(pred)[-1:] * max(0, n - len(pred))
        return list(pred), f"{model_name} with {len(feature_cols)} raw feature columns; validation={validation}"
    except Exception as exc:
        vals, method = baseline_values(train_df, target_col, n, sample_df[target_col_out] if target_col_out in sample_df else None)
        return vals, method + f" after model failure: {type(exc).__name__}: {exc}"


def make_submission(sample_path, train_path, test_path, out_dir, summaries):
    sample_df = read_table(sample_path)
    if pd is None or sample_df is None or not hasattr(sample_df, "copy"):
        out_path = out_dir / "submission.csv"
        text = sample_path.read_text(encoding="utf-8", errors="replace")
        out_path.write_text(text, encoding="utf-8")
        return str(out_path), {"status": "partial", "method": "copied sample submission because pandas was unavailable"}
    train_df = None
    test_df = None
    if train_path is not None:
        try:
            train_df = read_table(train_path)
        except Exception:
            train_df = None
    if test_path is not None:
        try:
            test_df = read_table(test_path)
        except Exception:
            test_df = None
    sub = sample_df.copy()
    sample_targets = infer_target_columns(sample_df, test_df)
    train_target = choose_train_target(train_df, sample_targets, test_df)
    methods = {}
    for out_col in sample_targets:
        pred, method = train_predict(train_df, test_df, train_target, sample_df, out_col)
        pred = coerce_to_sample_domain(pred, sample_df[out_col], train_df[train_target] if train_df is not None and train_target in train_df else None)
        sub[out_col] = list(pred)[:len(sub)]
        methods[out_col] = method
    out_path = out_dir / "submission.csv"
    sub = sub[[c for c in sample_df.columns]]
    sub.to_csv(out_path, index=False)
    valid = list(sub.columns) == list(sample_df.columns) and len(sub) == len(sample_df)
    id_cols = infer_id_columns(sample_df, test_df)
    if valid and id_cols:
        for col in id_cols:
            if not sub[col].astype(str).equals(sample_df[col].astype(str)):
                valid = False
    return str(out_path), {
        "status": "success" if valid else "partial",
        "method": methods,
        "train_file": str(train_path) if train_path else "",
        "test_file": str(test_path) if test_path else "",
        "sample_file": str(sample_path),
        "target_in_train": str(train_target) if train_target else "",
        "rows": int(len(sub)),
        "columns": list(sub.columns),
        "id_columns": id_cols,
        "target_columns": sample_targets,
    }


def numeric_metrics_from_table(name, df):
    metrics = []
    if pd is None or df is None or not hasattr(df, "select_dtypes"):
        return metrics
    numeric = df.select_dtypes(include="number")
    for col in numeric.columns[:40]:
        s = numeric[col].dropna()
        if len(s):
            metrics.append({
                "table": name,
                "metric": str(col),
                "count": int(len(s)),
                "mean": float(s.mean()),
                "median": float(s.median()),
                "min": float(s.min()),
                "max": float(s.max()),
                "std": float(s.std()) if len(s) > 1 else 0.0,
            })
    return metrics


def risk_or_credit_analysis(prompt, tables, out_dir):
    if pd is None or not tables:
        return None
    low_prompt = prompt.lower()
    wants_risk = any(w in low_prompt for w in ["risk", "credit", "invoice", "loan", "budget", "allocation", "churn", "rate", "pricing"])
    if not wants_risk:
        return None
    best_name, best_df = None, None
    for name, df in tables.items():
        if hasattr(df, "shape") and df.shape[0] >= 1 and df.shape[1] >= 2:
            best_name, best_df = name, df.copy()
            break
    if best_df is None:
        return None
    entity_col = None
    for c in best_df.columns:
        low = norm_name(c)
        if low in {"customer", "customer_id", "client", "client_id", "company", "entity", "entity_id", "account", "account_id", "vendor", "merchant", "borrower"} or low.endswith("_id"):
            entity_col = c
            break
    if entity_col is None:
        entity_col = best_df.columns[0]
    numeric_cols = [c for c in best_df.select_dtypes(include="number").columns if c != entity_col]
    group = best_df.groupby(entity_col, dropna=False)
    entity = pd.DataFrame({"entity": [str(x) for x in group.size().index], "record_count": group.size().values})
    for c in numeric_cols[:12]:
        agg = group[c].agg(["sum", "mean", "max"]).reset_index(drop=True)
        entity[f"{c}_sum"] = agg["sum"].values
        entity[f"{c}_mean"] = agg["mean"].values
        entity[f"{c}_max"] = agg["max"].values
    score = pd.Series(0.0, index=entity.index)
    for c in entity.columns:
        low = norm_name(c)
        if any(w in low for w in ["late", "overdue", "default", "risk", "churn", "failed", "unpaid", "debt"]):
            vals = pd.to_numeric(entity[c], errors="coerce").fillna(0)
            if vals.max() > vals.min():
                score += (vals - vals.min()) / (vals.max() - vals.min())
        if any(w in low for w in ["paid", "revenue", "amount", "sales", "value", "income"]):
            vals = pd.to_numeric(entity[c], errors="coerce").fillna(0)
            if vals.max() > vals.min():
                score -= 0.25 * ((vals - vals.min()) / (vals.max() - vals.min()))
    if score.max() > score.min():
        score = (score - score.min()) / (score.max() - score.min())
    entity["risk_score"] = score.round(6)
    entity["risk_tier"] = pd.cut(entity["risk_score"], bins=[-0.001, 0.33, 0.66, 1.001], labels=["low", "medium", "high"]).astype(str)
    budget_match = re.search(r"\$?\b([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:dollars?|usd|budget|allocation|allocate)?", prompt, re.I)
    budget = float(budget_match.group(1).replace(",", "")) if budget_match else 100000.0
    weights = (1.01 - entity["risk_score"]).clip(lower=0.05)
    entity["allocation"] = (weights / weights.sum() * budget).round(2) if weights.sum() else round(budget / len(entity), 2)
    diff = round(budget - float(entity["allocation"].sum()), 2)
    if len(entity):
        entity.loc[entity.index[0], "allocation"] = round(float(entity.loc[entity.index[0], "allocation"]) + diff, 2)
    rate_map = {"low": 0.08, "medium": 0.13, "high": 0.19}
    entity["suggested_rate"] = entity["risk_tier"].map(rate_map).astype(float)
    entity["risk_explanation"] = entity["risk_tier"].map({
        "low": "stronger observed metrics and lower adverse-signal score",
        "medium": "mixed metrics with moderate adverse-signal score",
        "high": "weaker observed metrics or elevated adverse-signal score",
    })
    entity = entity.sort_values(["risk_score", "entity"], ascending=[True, True])
    path = out_dir / "risk_scores.csv"
    entity.to_csv(path, index=False)
    tier = entity.groupby("risk_tier").agg(entity_count=("entity", "count"), allocation_sum=("allocation", "sum"), avg_rate=("suggested_rate", "mean"), avg_risk=("risk_score", "mean")).reset_index()
    tier_path = out_dir / "credit_allocation.csv"
    tier.to_csv(tier_path, index=False)
    return {"entity_table": str(path), "allocation_table": str(tier_path), "budget": budget, "entity_count": int(len(entity)), "source_table": best_name, "tier_counts": entity["risk_tier"].value_counts().to_dict()}


def make_chart(tables, out_dir):
    if pd is None or plt is None or not tables:
        return ""
    for name, df in tables.items():
        try:
            numeric = df.select_dtypes(include="number")
            if numeric.shape[1] == 0 or len(numeric) == 0:
                continue
            col = numeric.columns[0]
            fig = plt.figure(figsize=(7, 4))
            numeric[col].dropna().head(1000).hist(bins=30)
            plt.title(f"Distribution of {col}")
            plt.xlabel(str(col))
            plt.ylabel("count")
            plt.tight_layout()
            path = out_dir / "chart_numeric_distribution.png"
            fig.savefig(path)
            plt.close(fig)
            return str(path)
        except Exception:
            continue
    return ""


def write_metrics_csv(path, metrics):
    fields = ["table", "metric", "count", "mean", "median", "min", "max", "std"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in metrics:
            writer.writerow({k: row.get(k, "") for k in fields})


def build_report(prompt, files, summaries, metrics, submission_info, risk_info, chart_path, errors):
    lines = ["# Data Analysis Report", "", "## Problem understanding", prompt.strip() or "Analyze the provided data and produce benchmark-readable artifacts.", ""]
    lines += ["## Data discovered", "", "| file | rows | columns | notes |", "| --- | ---: | ---: | --- |"]
    for s in summaries:
        lines.append(f"| `{Path(s['path']).name}` | {s.get('rows', '')} | {s.get('columns', '')} | {', '.join(s.get('column_names', [])[:6])} |")
    if not summaries:
        lines.append("| (none) | 0 | 0 | No tabular data could be loaded. |")
    lines.append("")
    lines += ["## Data checks and key calculations", ""]
    if metrics:
        lines += ["| table | metric | count | mean | median | min | max |", "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
        for row in metrics[:30]:
            lines.append(f"| {row['table']} | {row['metric']} | {row['count']} | {row['mean']:.6g} | {row['median']:.6g} | {row['min']:.6g} | {row['max']:.6g} |")
    else:
        lines.append("No numeric columns were available for aggregate metric calculations, so outputs rely on schema checks and categorical summaries.")
    lines.append("")
    if submission_info:
        lines += ["## Submission artifact", "", f"Produced `submission.csv` with {submission_info.get('rows', 0)} rows and columns: {', '.join(submission_info.get('columns', []))}."]
        lines.append(f"Model or baseline: {submission_info.get('method')}")
        lines.append(f"Training target inferred: `{submission_info.get('target_in_train', '')}`.")
        lines.append("")
    if risk_info:
        lines += ["## Risk, credit, or allocation decisions", "", f"Entity-level decisions were computed from `{risk_info.get('source_table')}` for {risk_info.get('entity_count')} entities."]
        lines.append(f"Risk tiers use the rule: low <= 0.33, medium <= 0.66, high > 0.66 on a normalized adverse-signal score. Total allocation budget: {risk_info.get('budget')}.")
        lines.append(f"Tier counts: {risk_info.get('tier_counts')}.")
        lines.append("Machine-readable outputs: `risk_scores.csv` and `credit_allocation.csv`.")
        lines.append("")
    if chart_path:
        lines += ["## Chart", "", f"A numeric distribution chart was saved at `{Path(chart_path).name}`.", ""]
    lines += ["## Conclusions", ""]
    if submission_info and submission_info.get("status") == "success":
        lines.append("The submission schema was matched to the sample submission, including column order, row count, and identifier order.")
    elif risk_info:
        lines.append("The generated decision tables provide entity-level risk scores, tiers, allocations, and suggested pricing tied to observed adverse-signal metrics.")
    elif metrics:
        top = metrics[0]
        lines.append(f"The strongest available quantitative artifact is `{top['metric']}` from `{top['table']}`, with mean {top['mean']:.6g} across {top['count']} non-missing rows.")
    else:
        lines.append("The run produced a best-effort report, but limited readable tabular data prevented stronger quantitative conclusions.")
    lines += ["", "## Limitations", ""]
    lines.append("Column roles are inferred from filenames, sample submission schema, and common target/id names; hidden benchmark scoring labels are unavailable.")
    if errors:
        lines.append("Some files could not be loaded: " + "; ".join(errors[:5]))
    return "\n".join(lines) + "\n"


def main():
    workdir = Path(sys.argv[1]).resolve()
    out_dir = Path(sys.argv[2]).resolve()
    prompt = sys.argv[3] if len(sys.argv) > 3 else ""
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    errors = []
    status = "success"
    sample_path = None
    submission_path = ""
    try:
        files = discover_files(workdir)
        text_files = [p for p in files if p.suffix.lower() in {".md", ".txt"} or p.name.lower().startswith(("readme", "instructions"))]
        table_files = candidate_tables(files)
        sample_path = find_first(table_files, ["sample_submission"])
        train_path = find_first(table_files, ["train"])
        test_path = find_first(table_files, ["test"])
        if sample_path is not None and test_path == sample_path:
            test_path = None
        if test_path is None:
            for p in table_files:
                if p != sample_path and p != train_path and "test" in p.name.lower():
                    test_path = p
                    break
        summaries = []
        tables = {}
        for path in table_files[:30]:
            if path == sample_path:
                nrows = None
            else:
                nrows = None
            try:
                df = read_table(path, nrows=nrows)
                if df is None:
                    continue
                summaries.append(compact_summary(path, df))
                if pd is not None and hasattr(df, "shape"):
                    tables[path.name] = df
            except Exception as exc:
                errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
        sqlite_metrics = []
        for db in [p for p in files if p.suffix.lower() in {".sqlite", ".db"}][:10]:
            sqlite_metrics.extend(load_sqlite_metrics(db))
        metrics = []
        for name, df in list(tables.items())[:10]:
            metrics.extend(numeric_metrics_from_table(name, df))
        metrics_path = out_dir / "metrics.csv"
        write_metrics_csv(metrics_path, metrics)
        artifacts["metrics.csv"] = str(metrics_path)
        submission_info = None
        asks_submission = bool(re.search(r"submission|predict|kaggle|mle", prompt, re.I))
        if sample_path is not None or asks_submission:
            if sample_path is not None:
                submission_path, submission_info = make_submission(sample_path, train_path, test_path, out_dir, summaries)
                artifacts["submission.csv"] = submission_path
                if submission_info.get("status") != "success":
                    status = "partial"
            else:
                status = "partial"
                errors.append("Prompt asks for a submission, but no sample_submission file was found.")
        risk_info = risk_or_credit_analysis(prompt, tables, out_dir)
        if risk_info:
            artifacts["risk_scores.csv"] = risk_info["entity_table"]
            artifacts["credit_allocation.csv"] = risk_info["allocation_table"]
        chart_path = make_chart(tables, out_dir)
        if chart_path:
            artifacts["chart_numeric_distribution.png"] = chart_path
        analysis_summary = {
            "status": status,
            "prompt": prompt,
            "workdir": str(workdir),
            "files_discovered": [str(p.relative_to(workdir)) for p in files],
            "text_context_files": {str(p.relative_to(workdir)): read_text_limited(p, 3000) for p in text_files[:8]},
            "table_summaries": summaries,
            "sqlite_summaries": sqlite_metrics,
            "metric_count": len(metrics),
            "submission": submission_info,
            "risk_analysis": risk_info,
            "chart_path": chart_path,
            "errors": errors,
        }
        summary_path = out_dir / "analysis_summary.json"
        write_json(summary_path, analysis_summary)
        artifacts["analysis_summary.json"] = str(summary_path)
        report = build_report(prompt, files, summaries, metrics, submission_info, risk_info, chart_path, errors)
        report_path = out_dir / "REPORT.md"
        report_path.write_text(report, encoding="utf-8")
        artifacts["REPORT.md"] = str(report_path)
        response_path = out_dir / "response.md"
        response_path.write_text(report, encoding="utf-8")
        artifacts["response.md"] = str(response_path)
        if not summaries and not sqlite_metrics:
            status = "partial"
        result = {
            "status": status,
            "trajectory": str(out_dir / "trajectory.jsonl"),
            "artifacts": artifacts,
            "report_path": str(report_path),
            "submission_path": submission_path,
            "error": "; ".join(errors[:10]),
            "metrics": {"files": len(files), "tables_loaded": len(summaries), "numeric_metrics": len(metrics)},
        }
        result_path = out_dir / "result.json"
        write_json(result_path, result)
        artifacts["result.json"] = str(result_path)
        run_summary = {"status": status, "artifacts": artifacts, "report_path": str(report_path), "submission_path": submission_path, "errors": errors}
        write_json(out_dir / "run_summary.json", run_summary)
        print(json.dumps(run_summary))
        return 0
    except Exception as exc:
        status = "failed" if not artifacts else "partial"
        err = f"{type(exc).__name__}: {exc}"
        errors.append(err)
        traceback_text = traceback.format_exc()
        report_path = out_dir / "REPORT.md"
        report_path.write_text("# Data Analysis Report\n\nThe harness encountered an error after attempting discovery.\n\n" + err + "\n\n```\n" + traceback_text[-4000:] + "\n```\n", encoding="utf-8")
        summary_path = out_dir / "analysis_summary.json"
        write_json(summary_path, {"status": status, "errors": errors, "traceback": traceback_text})
        result = {"status": status, "trajectory": str(out_dir / "trajectory.jsonl"), "artifacts": {"REPORT.md": str(report_path), "analysis_summary.json": str(summary_path)}, "report_path": str(report_path), "submission_path": "", "error": err}
        write_json(out_dir / "result.json", result)
        write_json(out_dir / "run_summary.json", result)
        print(json.dumps(result))
        return 0 if status == "partial" else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


class GeneratedHarnessProgram:
    name = "generated-data-analysis"

    async def run(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        llm: Optional[object],
    ) -> HarnessResult:
        ctx.trajectory.log_step(0, phase="start", note=self.name)
        ctx.trajectory.log_step(1, phase="plan", note="discover data, run pandas analysis, validate artifacts")
        script = textwrap.dedent(ANALYSIS_SCRIPT)
        ok, result = await try_tool(
            ctx,
            tools,
            "python_exec",
            {
                "code": script,
                "argv": [str(ctx.workdir), str(ctx.out_dir), ctx.task.prompt or ""],
                "timeout": min(float(ctx.policy.max_tool_seconds), max(30.0, ctx.time_left() - 5.0)),
            },
        )
        ctx.step()
        run_summary = None
        error_obj = None
        if ok and result is not None and result.ok:
            ctx.trajectory.log_observation("analysis script completed", source="python_exec")
            try:
                stdout = (result.data or {}).get("stdout", "") if isinstance(result.data, dict) else ""
                last = [line for line in stdout.splitlines() if line.strip()][-1]
                run_summary = json.loads(last)
            except Exception:
                pass
        else:
            error_obj = result.error if result is not None else {"message": "python_exec unavailable"}
            ctx.trajectory.log_error(error_obj, step=ctx.budget.steps_used)

        summary_path = ctx.out_dir / "run_summary.json"
        if summary_path.exists():
            try:
                run_summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        if run_summary is None:
            report = (
                "# Data Analysis Report\n\n"
                "The scaffold python execution step did not complete successfully. "
                "A best-effort failure artifact was written for diagnosis.\n"
            )
            report_path = ctx.new_artifact_text("REPORT.md", report, kind="markdown")
            response_path = ctx.new_artifact_text("response.md", report, kind="markdown")
            result_obj = {
                "status": "failed",
                "trajectory": str(ctx.out_dir / "trajectory.jsonl"),
                "artifacts": {"REPORT.md": str(report_path), "response.md": str(response_path)},
                "report_path": str(report_path),
                "submission_path": "",
                "error": json.dumps(error_obj or "analysis failed", ensure_ascii=False),
            }
            result_path = ctx.new_artifact_json("result.json", result_obj)
            return make_result(ctx, status="failed", answer_path=response_path, error_path=result_path, metadata={"program": self.name, "error": error_obj})

        artifacts = run_summary.get("artifacts") or {}
        for name, raw_path in artifacts.items():
            try:
                path = Path(raw_path)
                if path.exists() and path.resolve().is_relative_to(ctx.out_dir.resolve()):
                    kind = "file"
                    if path.suffix.lower() == ".json":
                        kind = "json"
                    elif path.suffix.lower() in {".md", ".txt"}:
                        kind = "text"
                    elif path.suffix.lower() == ".csv":
                        kind = "csv"
                    elif path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                        kind = "image"
                    ctx.artifact_store.register(name, path, kind=kind)
                    ctx.trajectory.log_artifact(name, path, kind=kind, step=ctx.budget.steps_used)
            except Exception:
                continue

        if tools.has("domain_artifact_validator"):
            await try_tool(ctx, tools, "domain_artifact_validator", {"domain": "data_analysis", "workdir": str(ctx.workdir), "out_dir": str(ctx.out_dir)})

        ctx.trajectory.log_step(2, phase="verify", note="registered output artifacts and ran public contract validator")
        report_path = Path(run_summary.get("report_path") or ctx.out_dir / "REPORT.md")
        response_path = ctx.out_dir / "response.md"
        if not response_path.exists() and report_path.exists():
            response_path.write_text(report_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            ctx.artifact_store.register("response.md", response_path, kind="markdown")
        status = str(run_summary.get("status") or "partial")
        harness_status = "success" if status in {"success", "partial"} else "failed"
        ctx.trajectory.log_step(3, phase="done", note=status)
        return make_result(
            ctx,
            status=harness_status,  # type: ignore[arg-type]
            answer_path=response_path if response_path.exists() else report_path,
            metadata={
                "program": self.name,
                "data_status": status,
                "submission_path": run_summary.get("submission_path", ""),
                "report_path": str(report_path),
                "errors": run_summary.get("errors", []),
            },
        )


PROGRAM = GeneratedHarnessProgram()


def get_program() -> GeneratedHarnessProgram:
    return PROGRAM
