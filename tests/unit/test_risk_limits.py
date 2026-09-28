from pathlib import Path

import pandas as pd
import pytest

from concrisk.risk import Breach, evaluate_limits, load_limits
from concrisk.risk.limits import LimitsConfig

LIMITS_YAML = Path("limits.yaml")
BERK_CIK = "0001067983"
OTHER_CIK = "0001350694"


@pytest.fixture(scope="module")
def cfg() -> LimitsConfig:
    return load_limits(LIMITS_YAML)


def test_load_limits_parses_rules_and_overrides(cfg: LimitsConfig) -> None:
    # HAND-COMPUTED: limits.yaml has 5 rules (single_issuer, top10, sector,
    # hhi, min_effective_n) and 1 override for Berkshire (CIK 1067983,
    # single_issuer → warning 0.30, breach 0.40).
    assert len(cfg.rules) == 5
    rule_ids = {r.id for r in cfg.rules}
    assert rule_ids == {"single_issuer", "top10", "sector", "hhi", "min_effective_n"}

    # Override CIK is stored normalized to `str(int(cik))` — no leading zeros.
    assert "1067983" in cfg.overrides
    assert cfg.overrides["1067983"]["single_issuer"] == {"warning": 0.30, "breach": 0.40}

    # sector rule carries its exclude list.
    sector_rule = next(r for r in cfg.rules if r.id == "sector")
    assert sector_rule.exclude == ("Unclassified",)

    # top10 rule carries its params.
    top10_rule = next(r for r in cfg.rules if r.id == "top10")
    assert top10_rule.params == {"n": 10}

    # min_effective_n uses direction=below.
    min_n_rule = next(r for r in cfg.rules if r.id == "min_effective_n")
    assert min_n_rule.direction == "below"


def _find(breaches: list[Breach], rule_id: str, scope_key: str | None = None) -> Breach:
    matches = [b for b in breaches if b.rule_id == rule_id and b.scope_key == scope_key]
    assert len(matches) == 1, (
        f"expected 1 breach for {rule_id}/{scope_key}, got {len(matches)}: {matches}"
    )
    return matches[0]


def _no_breach(breaches: list[Breach], rule_id: str, scope_key: str | None = None) -> None:
    matches = [b for b in breaches if b.rule_id == rule_id and b.scope_key == scope_key]
    assert not matches, f"expected no breach for {rule_id}/{scope_key}, got {matches}"


def test_hhi_warning_when_between_thresholds(cfg: LimitsConfig) -> None:
    # HAND-COMPUTED: hhi rule warning=0.10 breach=0.15. Observed 0.12 is
    # ≥ 0.10 and < 0.15 → warning, not breach.
    breaches = evaluate_limits(
        cfg,
        fund_cik=OTHER_CIK,
        quarter="2026Q1",
        weights=pd.Series([1.0]),
        issuer_wts=pd.Series(dtype=float),
        sector_wts=pd.Series(dtype=float),
        hhi_value=0.12,
        effective_n_value=100.0,
    )
    b = _find(breaches, "hhi")
    assert b.severity == "warning"
    assert b.threshold == 0.10
    assert b.observed == 0.12


def test_hhi_breach_when_above_top_threshold(cfg: LimitsConfig) -> None:
    # HAND-COMPUTED: 0.20 ≥ 0.15 → breach.
    breaches = evaluate_limits(
        cfg,
        fund_cik=OTHER_CIK,
        quarter="2026Q1",
        weights=pd.Series([1.0]),
        issuer_wts=pd.Series(dtype=float),
        sector_wts=pd.Series(dtype=float),
        hhi_value=0.20,
        effective_n_value=100.0,
    )
    b = _find(breaches, "hhi")
    assert b.severity == "breach"
    assert b.threshold == 0.15


def test_single_issuer_scope_emits_per_issuer(cfg: LimitsConfig) -> None:
    # HAND-COMPUTED: default single_issuer thresholds 0.08/0.10.
    # AAPL 0.12 → breach; BAC 0.09 → warning; MSFT 0.05 → no breach.
    issuer_wts = pd.Series({"AAPL": 0.12, "BAC": 0.09, "MSFT": 0.05})
    breaches = evaluate_limits(
        cfg,
        fund_cik=OTHER_CIK,
        quarter="2026Q1",
        weights=pd.Series(list(issuer_wts.values)),
        issuer_wts=issuer_wts,
        sector_wts=pd.Series(dtype=float),
        hhi_value=0.05,
        effective_n_value=100.0,
    )
    aapl = _find(breaches, "single_issuer", "AAPL")
    bac = _find(breaches, "single_issuer", "BAC")
    assert aapl.severity == "breach"
    assert aapl.threshold == 0.10
    assert bac.severity == "warning"
    assert bac.threshold == 0.08
    _no_breach(breaches, "single_issuer", "MSFT")


def test_sector_rule_excludes_unclassified(cfg: LimitsConfig) -> None:
    # HAND-COMPUTED: sector thresholds 0.30/0.40. Unclassified in exclude
    # list, so its 0.35 does NOT trigger. Tech at 0.45 → breach; Fin at
    # 0.20 → no breach.
    sector_wts = pd.Series({"Tech": 0.45, "Financials": 0.20, "Unclassified": 0.35})
    breaches = evaluate_limits(
        cfg,
        fund_cik=OTHER_CIK,
        quarter="2026Q1",
        weights=pd.Series([1.0]),
        issuer_wts=pd.Series(dtype=float),
        sector_wts=sector_wts,
        hhi_value=0.05,
        effective_n_value=100.0,
    )
    tech = _find(breaches, "sector", "Tech")
    assert tech.severity == "breach"
    assert tech.threshold == 0.40
    _no_breach(breaches, "sector", "Financials")
    _no_breach(breaches, "sector", "Unclassified")


def test_min_effective_n_direction_below(cfg: LimitsConfig) -> None:
    # HAND-COMPUTED: min_effective_n direction=below, warning=15,
    # breach=10. Observed 8 ≤ 10 → breach. Observed 12 is ≤ 15 but
    # > 10 → warning. Observed 20 → no breach.
    for observed, expected_severity, expected_threshold in [
        (8.0, "breach", 10),
        (12.0, "warning", 15),
    ]:
        breaches = evaluate_limits(
            cfg,
            fund_cik=OTHER_CIK,
            quarter="2026Q1",
            weights=pd.Series([1.0]),
            issuer_wts=pd.Series(dtype=float),
            sector_wts=pd.Series(dtype=float),
            hhi_value=0.05,
            effective_n_value=observed,
        )
        b = _find(breaches, "min_effective_n")
        assert b.severity == expected_severity
        assert b.threshold == expected_threshold

    # 20 > both thresholds → no breach.
    breaches = evaluate_limits(
        cfg,
        fund_cik=OTHER_CIK,
        quarter="2026Q1",
        weights=pd.Series([1.0]),
        issuer_wts=pd.Series(dtype=float),
        sector_wts=pd.Series(dtype=float),
        hhi_value=0.05,
        effective_n_value=20.0,
    )
    _no_breach(breaches, "min_effective_n")


def test_berkshire_override_relaxes_single_issuer(cfg: LimitsConfig) -> None:
    # HAND-COMPUTED: Berkshire's override raises single_issuer to
    # warning=0.30, breach=0.40. AAPL at 0.35 → warning (would be a
    # breach at default 0.10). A generic fund (no override) sees the
    # same 0.35 as a breach against 0.10.
    issuer_wts = pd.Series({"AAPL": 0.35})

    berk = evaluate_limits(
        cfg,
        fund_cik=BERK_CIK,
        quarter="2026Q1",
        weights=pd.Series([1.0]),
        issuer_wts=issuer_wts,
        sector_wts=pd.Series(dtype=float),
        hhi_value=0.05,
        effective_n_value=100.0,
    )
    b_berk = _find(berk, "single_issuer", "AAPL")
    assert b_berk.severity == "warning"
    assert b_berk.threshold == 0.30

    other = evaluate_limits(
        cfg,
        fund_cik=OTHER_CIK,
        quarter="2026Q1",
        weights=pd.Series([1.0]),
        issuer_wts=issuer_wts,
        sector_wts=pd.Series(dtype=float),
        hhi_value=0.05,
        effective_n_value=100.0,
    )
    b_other = _find(other, "single_issuer", "AAPL")
    assert b_other.severity == "breach"
    assert b_other.threshold == 0.10


def test_override_cik_normalization_ignores_leading_zeros(cfg: LimitsConfig) -> None:
    # HAND-COMPUTED: overrides key is "1067983" (int-cast) in limits.yaml;
    # our fund CIK is "0001067983". Normalizer must strip leading zeros
    # on lookup for the override to apply. Uses the same AAPL 0.35 case.
    issuer_wts = pd.Series({"AAPL": 0.35})
    for cik in ("1067983", "0001067983", "00001067983"):  # any padding
        breaches = evaluate_limits(
            cfg,
            fund_cik=cik,
            quarter="2026Q1",
            weights=pd.Series([1.0]),
            issuer_wts=issuer_wts,
            sector_wts=pd.Series(dtype=float),
            hhi_value=0.05,
            effective_n_value=100.0,
        )
        b = _find(breaches, "single_issuer", "AAPL")
        assert b.severity == "warning", f"cik={cik} should hit override"
