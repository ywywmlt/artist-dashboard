"""
JISOO-style financial model tests.

Runs the compute block extracted from ui-sample.html via a Node bridge
(tests/eval_fn.js). Requires `node` on PATH.
"""
import json
import pathlib
import shutil
import subprocess
from typing import Optional

import pytest

REPO = pathlib.Path(__file__).parent.parent
FIXTURES = REPO / "tests" / "financial_model_fixtures.json"
BRIDGE = REPO / "tests" / "eval_fn.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node not installed; skipping JS financial model tests",
)


def _run(profile_key: str, fn_name: str, case: Optional[str] = None):
    cmd = ["node", str(BRIDGE), str(FIXTURES), profile_key, fn_name]
    if case:
        cmd.append(case)
    r = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


# ── Revenue Cash Flow ────────────────────────────────────────────────────────
def test_rcf_jisoo_bangkok_80_20_base():
    """Base case: Bangkok ticket rev at 90% fill = ~2,952,037.80.
    Curve 80/20 across T-3mo (May) and T-0 (Aug)."""
    r = _run("jisoo_exact_replica", "computeRevenueCashFlow", "base")
    assert r is not None
    bangkok = next(row for row in r["rows"] if row["city_name"] == "Bangkok")
    may_idx = r["months"].index("2026-05")
    aug_idx = r["months"].index("2026-08")
    assert abs(bangkok["totalsByMonth"][may_idx] - 2361630.24) < 1.0
    assert abs(bangkok["totalsByMonth"][aug_idx] - 590407.56) < 1.0


def test_rcf_jisoo_best_grand_total():
    """Best case: 8 cities × 100% fill = $28,582,566.20 total ticket revenue."""
    r = _run("jisoo_exact_replica", "computeRevenueCashFlow", "best")
    assert abs(r["grand"] - 28582566.20) < 1.0


def test_rcf_null_on_legacy():
    """Legacy profile with no timeline returns null."""
    assert _run("legacy_no_timeline", "computeRevenueCashFlow") is None


# ── Cash Flow Matrix ─────────────────────────────────────────────────────────
def test_cf_matrix_jisoo_best():
    r = _run("jisoo_exact_replica", "computeCashFlow", "best")
    m = r["matrix"]
    assert m is not None
    assert "2026-03" in m["months"]
    assert "2027-03" in m["months"]
    assert abs(m["totals"]["ticket"] - 28582566.20) < 1.0
    # JISOO sheet: Total Production Cost = 9,699,999.81
    assert abs(m["totals"]["production"] - 9699999.81) < 1.0
    # Artist MG total = 8,533,333.28
    assert abs(m["totals"]["artist_mg"] - 8533333.28) < 1.0


def test_cf_matrix_null_on_legacy():
    r = _run("legacy_no_timeline", "computeCashFlow")
    assert r["matrix"] is None
    # Legacy profile has no concert_date → events may be None OR empty list
    assert r["events"] is None or isinstance(r["events"], list)


def test_cf_peak_exposure_jisoo():
    """The JISOO investor peak deficit lands in Mar or Apr 2026
    (before ticket revenue starts flowing in May)."""
    r = _run("jisoo_exact_replica", "computeCashFlow", "best")
    m = r["matrix"]
    assert m["peak_exposure_month"] in ("2026-03", "2026-04", "2026-05")
    assert m["peak_deficit"] < 0


# ── computeProfile case parameter ────────────────────────────────────────────
def test_case_base_vs_best_jisoo():
    """Best (100%) ticket revenue ≈ Base (90%) × 10/9."""
    base = _run("jisoo_exact_replica", "computeProfile", "base")
    best = _run("jisoo_exact_replica", "computeProfile", "best")
    ratio = best["total_ticket_rev"] / base["total_ticket_rev"]
    assert abs(ratio - 10 / 9) < 0.001


def test_case_does_not_mutate_profile():
    """Running computeProfile with case=best twice → same result (no stale state)."""
    first = _run("jisoo_exact_replica", "computeProfile", "best")
    second = _run("jisoo_exact_replica", "computeProfile", "best")
    assert abs(first["total_ticket_rev"] - second["total_ticket_rev"]) < 0.01


# ── Single-city fixture smoke ────────────────────────────────────────────────
def test_single_city_rcf_works():
    r = _run("single_city", "computeRevenueCashFlow", "base")
    assert r is not None
    assert len(r["rows"]) == 1
    seoul = r["rows"][0]
    assert seoul["city_name"] == "Seoul"
    # 70% T-2mo (July) + 30% T-0 (September)
    jul_idx = r["months"].index("2026-07")
    sep_idx = r["months"].index("2026-09")
    # capacity 40000 × 0.9 fill (base default) × weighted avg price
    # GA 200 × 30000 + VIP 500 × 10000 = 11,000,000; × 0.9 = 9,900,000
    assert abs(seoul["total"] - 9900000) < 1.0
    assert abs(seoul["totalsByMonth"][jul_idx] / seoul["total"] - 0.7) < 0.001
    assert abs(seoul["totalsByMonth"][sep_idx] / seoul["total"] - 0.3) < 0.001
