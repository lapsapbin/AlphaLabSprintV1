"""Reproducible Day 2 entrypoint; read only through 2017 before computation."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import time

import pandas as pd

from .access import load_config, load_research
from .data import read_manifest, sha256, utc_now, verify_raw, write_json
from .diagnostics import research_diagnostics
from .signals import momentum_12_2, ranked_signals, return_panel, target_weights
from .validation import require

# Accepted Day 1 manifest, immutable for this work package (includes all file hashes).
DAY1_MANIFEST_SHA256 = "4c46e55a1ad89b930f2092e64fd731437b2c11b6dcd442f6f4d2307025369b61"


def verify_day2_snapshot(root: Path) -> dict:
    require(sha256((root / "data/manifest.json").read_bytes()) == DAY1_MANIFEST_SHA256, "accepted_day1_manifest_changed")
    manifest = read_manifest(root)
    verify_raw(root, manifest)
    for relative, record in manifest["products"].items():
        require(sha256((root / relative).read_bytes()) == record["sha256"], "processed_hash_mismatch")
    return manifest


def source_hashes(root: Path) -> dict:
    return {str(path.relative_to(root)): sha256(path.read_bytes()) for path in sorted((root / "src/alphalab").glob("*.py"))}


def _git(root: Path, *args: str) -> str | None:
    if not (root / ".git").exists():
        return None  # A review directory must not inherit an unrelated parent repo.
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def _csv(table: pd.DataFrame) -> bytes:
    # 17 significant digits preserve binary floating-point results on CSV roundtrip.
    return table.to_csv(index=False, float_format="%.17g", na_rep="", lineterminator="\n").encode("utf-8")


def run_signals(root: Path, end: str = "2017-12") -> dict:
    start_clock = time.perf_counter()
    config = load_config(root)
    require(config["phase"] == "DAY2", "day2_phase_required")
    require(pd.Period(end, "M") <= pd.Period("2017-12", "M"), "DAY2_RESEARCH_LOCKED_AFTER_2017_12")
    require(end == "2017-12", "day2_fixed_research_end_required")
    require(config["design"]["top_n"] == 5 and config["design"]["momentum_lags"] == [12, 2]
            and config["design"]["industry_allocation"] == "equal_weight"
            and config["design"]["tie_break"] == "normalized_label_ascending", "day2_frozen_design_required")
    # All-file hash verification is byte/ZIP integrity only; no full-sample signal,
    # diagnostic or return statistic is calculated.
    manifest = verify_day2_snapshot(root)
    status = _git(root, "status", "--porcelain=v1")
    dirty = bool(status) if status is not None else None
    industries, _ = load_research(root, start="1998-01", end="2017-12")
    require(industries["month"].between(pd.Period("1998-01", "M"), pd.Period("2017-12", "M")).all(), "day2_loaded_range")
    require(len(industries) == 240 * 49, "day2_input_row_count")
    panel = return_panel(industries, config["data"]["labels"])
    require(panel.index.equals(pd.period_range("1998-01", "2017-12", freq="M")), "day2_input_calendar")
    signals = momentum_12_2(panel, pd.period_range("1999-01", "2017-12", freq="M"), config["data"]["labels"])
    ic, quintiles, summary = research_diagnostics(signals, panel)
    tables = {"momentum_12_2.csv": ranked_signals(signals), "target_weights.csv": target_weights(signals),
              "rank_ic_research.csv": ic, "quintile_returns_research.csv": quintiles}
    payloads = {name: _csv(table) for name, table in tables.items()}
    payloads["diagnostic_summary.json"] = (json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    output = root / "outputs/day2"
    # Never silently replace a previously generated numerical result.
    for name, payload in payloads.items():
        require(not (output / name).exists() or (output / name).read_bytes() == payload, "day2_existing_output_mismatch")
    output.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        if not (output / name).exists():
            (output / name).write_bytes(payload)
    hashes = source_hashes(root)
    run_manifest = {
        "stage": "DAY2", "source_hashes": hashes,
        "source_tree_sha256": sha256(json.dumps(hashes, sort_keys=True).encode()),
        "config_sha256": sha256((root / "config/research.yaml").read_bytes()),
        "uv_lock_sha256": sha256((root / "uv.lock").read_bytes()),
        "input_manifest_sha256": DAY1_MANIFEST_SHA256,
        "input_snapshot_hashes": {key: value["sha256"] for key, value in manifest["files"].items()},
        "processed_hashes": {key: value["sha256"] for key, value in manifest["products"].items()},
        "research_input_range": ["1998-01", "2017-12"], "worktree_dirty": dirty,
        "parameters": {"momentum_lags": [12, 2], "window_months": 11, "skip_lag": 1, "top_n": 5,
                       "tie_break": "normalized_label_ascending", "IC_ties": "average_rank",
                       "quintile_sizes": [10, 10, 10, 10, 9]},
        "holdout_status": "LOCKED", "validation_performance_evaluated": False,
        "outputs": {name: {"sha256": sha256(payload), "bytes": len(payload),
                           **({"rows": len(tables[name]), "range": [str(tables[name]["holding_month"].min()), str(tables[name]["holding_month"].max())]}
                              if name in tables else {"range": summary["range"]})} for name, payload in payloads.items()},
    }
    write_json(output / "run_manifest.json", run_manifest)
    execution = {"recorded_at_utc": utc_now(), "elapsed_seconds": time.perf_counter() - start_clock,
                 "local_commit": _git(root, "rev-parse", "HEAD"), "worktree_dirty": dirty,
                 "run_manifest_sha256": sha256((output / "run_manifest.json").read_bytes())}
    with (output / "run_execution.jsonl").open("a") as handle:
        handle.write(json.dumps(execution, sort_keys=True) + "\n")
    return {"status": "PASS", "signal_range": ["1999-01", "2017-12"], "signal_rows": len(tables["momentum_12_2.csv"]),
            "weight_rows": len(tables["target_weights.csv"]), "research_summary": summary,
            "OOS": "LOCKED", "validation_performance_evaluated": False}


FROZEN_DESIGN = {
    "top_n": 5, "momentum_lags": [12, 2], "industry_allocation": "equal_weight",
    "tie_break": "normalized_label_ascending", "costs_bps_one_way": [0, 10, 20],
    "main_cost_bps": 10, "risk_target_annual": 0.10, "risk_lookback_months": 12,
    "risk_ddof": 1, "leverage_cap": 1.0,
    "strategies": ["MOM5", "MOM5_VOL10", "EW49", "EW49_VOL10"], "hac_lags": 6,
    "sensitivities": [{"top_n": 10, "momentum_lags": [12, 2], "cost_bps": 10},
                      {"top_n": 5, "momentum_lags": [6, 2], "cost_bps": 10}],
}


def run_backtest(root: Path, end: str = "2017-12") -> dict:
    """Day3 only: fixed 12 scenarios, with fresh cash only at 2000-01."""
    import importlib.metadata
    import platform
    import numpy as np
    from .backtest import simulate
    from .metrics import performance, summaries
    from .portfolio import BASES, STRATEGIES, base_gross_returns, risk_targets

    started = time.perf_counter()
    config = load_config(root)
    require(config["phase"] == "DAY3", "day3_phase_required")
    require(pd.Period(end, "M") <= pd.Period("2017-12", "M"), "DAY3_RESEARCH_LOCKED_AFTER_2017_12")
    require(end == "2017-12", "day3_fixed_research_end_required")
    require(config["design"] == FROZEN_DESIGN, "day3_frozen_design_required")
    snapshot = verify_day2_snapshot(root)  # The same accepted Day1 bytes; no data acquisition.
    status = _git(root, "status", "--porcelain=v1")
    dirty = bool(status) if status is not None else None
    industries, factors = load_research(root, start="1998-01", end="2017-12")
    panel = return_panel(industries, config["data"]["labels"])
    require(panel.index.equals(pd.period_range("1998-01", "2017-12", freq="M")) and len(industries) == 240 * 49, "day3_input_calendar")
    require(not factors.month.duplicated().any(), "factor_duplicate_month")
    factors = factors.set_index("month")
    require(factors.index.equals(panel.index), "day3_factor_calendar")
    signal_calendar = pd.period_range("1999-01", "2017-12", freq="M")
    calendar = pd.period_range("2000-01", "2017-12", freq="M")
    signals = momentum_12_2(panel, signal_calendar, config["data"]["labels"])
    long_base = target_weights(signals)
    base_weights = {base: long_base.loc[long_base.strategy == base].pivot(
        index="holding_month", columns="industry", values="weight").sort_index() for base in BASES}
    base_gross = base_gross_returns(base_weights, panel)
    targets, risk = risk_targets(base_weights, base_gross, calendar)
    results, drifts, states, target_tables = [], [], {}, []
    rf = factors.loc[calendar, "RF"]
    for strategy in STRATEGIES:
        risk_view = risk.loc[risk.strategy == strategy].set_index("holding_month")
        target_long = targets[strategy].rename_axis("holding_month").reset_index().melt(
            id_vars="holding_month", var_name="industry", value_name="weight")
        target_long["strategy"] = strategy
        target_tables.append(target_long)
        for cost in (0, 10, 20):
            monthly, drift, state = simulate(targets[strategy], panel.loc[calendar], rf, cost)
            monthly["strategy"], monthly["cost_bps"] = strategy, cost
            monthly["risk_scale"] = monthly.holding_month.map(risk_view.risk_scale)
            monthly["sigma_annual"] = monthly.holding_month.map(risk_view.sigma_annual)
            results.append(monthly)
            # Drift is cost-invariant: k cancels. Save once per strategy, check all scenarios.
            if cost == 0:
                reference_drift = drift
                drift["strategy"] = strategy
                drifts.append(drift)
            else:
                require(reference_drift.drop(columns="strategy").equals(drift), "cost_scenario_drift_changed")
            states[f"{strategy}:{cost}"] = state.to_dict()
    monthly = pd.concat(results, ignore_index=True).sort_values(["holding_month", "strategy", "cost_bps"]).reset_index(drop=True)
    summary, active, differences = summaries(monthly)
    market_return = (factors.loc[calendar, "Mkt-RF"] + rf).to_numpy(dtype=float)
    require(np.isfinite(market_return).all() and (market_return > -1).all(), "market_reference_returns")
    market_nav = np.cumprod(1 + market_return)
    market = pd.DataFrame({"holding_month": calendar, "reference": "Mkt-RF+RF (no fees)",
                           "total_return": market_return, "RF": rf.to_numpy(), "nav": market_nav})
    market_summary = pd.DataFrame([{"reference": "Mkt-RF+RF (no fees; not an ETF)",
                                   **performance(market_return, rf.to_numpy(), market_nav)}])
    tables = {
        "monthly_results.csv": monthly, "performance_summary.csv": summary,
        "target_weights.csv": pd.concat(target_tables, ignore_index=True).sort_values(["holding_month", "strategy", "industry"]),
        "base_gross_returns.csv": base_gross.reset_index(), "risk_estimates.csv": risk,
        "drift_weights.csv": pd.concat(drifts, ignore_index=True).sort_values(["holding_month", "strategy", "industry"]),
        "active_returns.csv": active.sort_values(["holding_month", "strategy", "cost_bps", "benchmark"]),
        "active_summary.csv": differences, "market_reference.csv": market,
        "market_reference_summary.csv": market_summary,
    }
    # Plain state plus exactly the history needed for next-month signals/risk.
    # No checkpoint framework and no validation/OOS evaluation is introduced.
    signal_history = panel.iloc[-12:].reset_index()
    signal_history["month"] = signal_history["month"].astype(str)
    risk_history = base_gross.iloc[-12:].reset_index()
    risk_history["holding_month"] = risk_history["holding_month"].astype(str)
    terminal = {"last_month": "2017-12", "states": states,
                "signal_return_history": signal_history.to_dict("records"),
                "base_gross_history": risk_history.to_dict("records"),
                "continuation_rule": "Next segment must continue last_month+1, NAV and drift; never reset."}
    payloads = {name: _csv(table) for name, table in tables.items()}
    payloads["terminal_state.json"] = (json.dumps(terminal, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    output = root / "outputs/day3"
    for name, payload in payloads.items():
        require(not (output / name).exists() or (output / name).read_bytes() == payload, "day3_existing_output_mismatch")
    output.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        if not (output / name).exists():
            (output / name).write_bytes(payload)
    hashes = source_hashes(root)
    output_info = {}
    for name, payload in payloads.items():
        info = {"sha256": sha256(payload), "bytes": len(payload)}
        if name in tables:
            info["rows"] = len(tables[name])
            if "holding_month" in tables[name]:
                info["range"] = [str(tables[name].holding_month.min()), str(tables[name].holding_month.max())]
            else:
                info["range"] = ["2000-01", "2017-12"]
        else:
            info["history_range"] = ["2017-01", "2017-12"]
        output_info[name] = info
    run_manifest = {
        "stage": "DAY3", "source_hashes": hashes,
        "source_tree_sha256": sha256(json.dumps(hashes, sort_keys=True).encode()),
        "config_sha256": sha256((root / "config/research.yaml").read_bytes()),
        "uv_lock_sha256": sha256((root / "uv.lock").read_bytes()),
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "dependencies": {name: importlib.metadata.version(name) for name in ("numpy", "pandas", "PyYAML", "pytest")}},
        "input_manifest_sha256": DAY1_MANIFEST_SHA256,
        "input_snapshot_hashes": {name: record["sha256"] for name, record in snapshot["files"].items()},
        "processed_hashes": {name: record["sha256"] for name, record in snapshot["products"].items()},
        "parameters": FROZEN_DESIGN, "research_input_range": ["1998-01", "2017-12"],
        "base_warmup_range": ["1999-01", "1999-12"], "scored_range": ["2000-01", "2017-12"],
        "initial_state": "all cash, NAV=1 at 2000-01; initial trades charged", "terminal_liquidation": False,
        "worktree_dirty": dirty, "holdout_status": "LOCKED", "validation_performance_evaluated": False,
        "outputs": output_info,
    }
    write_json(output / "run_manifest.json", run_manifest)
    execution = {"recorded_at_utc": utc_now(), "elapsed_seconds": time.perf_counter() - started,
                 "local_commit": _git(root, "rev-parse", "HEAD"), "worktree_dirty": dirty,
                 "run_manifest_sha256": sha256((output / "run_manifest.json").read_bytes())}
    with (output / "run_execution.jsonl").open("a") as handle:
        handle.write(json.dumps(execution, sort_keys=True) + "\n")
    return {"status": "PASS", "scored_range": ["2000-01", "2017-12"], "months": 216,
            "scenarios": 12, "monthly_rows": len(monthly),
            "main_10bps": summary.loc[summary.cost_bps == 10].to_dict("records"),
            "OOS": "LOCKED", "validation_performance_evaluated": False}
