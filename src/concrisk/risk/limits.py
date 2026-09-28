from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import yaml

from concrisk.risk.concentration import top_n_weight

Severity = Literal["warning", "breach"]
Direction = Literal["above", "below"]


@dataclass(frozen=True)
class Rule:
    id: str
    description: str
    metric: str
    warning: float | None = None
    breach: float | None = None
    direction: Direction = "above"
    scope: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class Breach:
    fund_cik: str
    quarter: str
    rule_id: str
    metric: str
    observed: float
    threshold: float
    severity: Severity
    scope_key: str | None


@dataclass(frozen=True)
class LimitsConfig:
    defaults: dict[str, Any]
    rules: tuple[Rule, ...]
    overrides: dict[str, dict[str, dict[str, float]]]


def load_limits(path: Path) -> LimitsConfig:
    """Parse limits.yaml into a typed LimitsConfig. Override keys are
    normalized to `str(int(cik))` (no leading zeros) — matches the shape
    the YAML uses; callers pass CIK in any form and the evaluator
    normalizes at lookup time."""
    data = yaml.safe_load(Path(path).read_text()) or {}
    raw_rules = data.get("rules") or []
    rules = tuple(_parse_rule(r) for r in raw_rules)

    raw_overrides = data.get("overrides") or {}
    overrides: dict[str, dict[str, dict[str, float]]] = {}
    for cik_key, rule_overrides in raw_overrides.items():
        cik_norm = str(int(str(cik_key)))
        overrides[cik_norm] = dict(rule_overrides or {})

    return LimitsConfig(
        defaults=dict(data.get("defaults") or {}),
        rules=rules,
        overrides=overrides,
    )


def _parse_rule(r: dict[str, Any]) -> Rule:
    return Rule(
        id=r["id"],
        description=r.get("description", ""),
        metric=r["metric"],
        warning=r.get("warning"),
        breach=r.get("breach"),
        direction=r.get("direction", "above"),
        scope=r.get("scope"),
        params=dict(r.get("params") or {}),
        exclude=tuple(r.get("exclude") or ()),
    )


def _rule_for_fund(
    rule: Rule,
    fund_cik: str,
    overrides: dict[str, dict[str, dict[str, float]]],
) -> Rule:
    cik_norm = str(int(fund_cik))
    override = overrides.get(cik_norm, {}).get(rule.id)
    if not override:
        return rule
    return replace(
        rule,
        warning=override.get("warning", rule.warning),
        breach=override.get("breach", rule.breach),
    )


def _crosses(observed: float, threshold: float, direction: Direction) -> bool:
    if direction == "below":
        return observed <= threshold
    return observed >= threshold


def _emit(
    out: list[Breach],
    rule: Rule,
    fund_cik: str,
    quarter: str,
    observed: float,
    scope_key: str | None,
) -> None:
    """Append at most one Breach per (rule, scope_key). Higher severity wins."""
    if rule.breach is not None and _crosses(observed, rule.breach, rule.direction):
        out.append(
            Breach(
                fund_cik=fund_cik,
                quarter=quarter,
                rule_id=rule.id,
                metric=rule.metric,
                observed=observed,
                threshold=rule.breach,
                severity="breach",
                scope_key=scope_key,
            )
        )
        return
    if rule.warning is not None and _crosses(observed, rule.warning, rule.direction):
        out.append(
            Breach(
                fund_cik=fund_cik,
                quarter=quarter,
                rule_id=rule.id,
                metric=rule.metric,
                observed=observed,
                threshold=rule.warning,
                severity="warning",
                scope_key=scope_key,
            )
        )


def evaluate_limits(
    config: LimitsConfig,
    *,
    fund_cik: str,
    quarter: str,
    weights: pd.Series,
    issuer_wts: pd.Series,
    sector_wts: pd.Series,
    hhi_value: float,
    effective_n_value: float,
) -> list[Breach]:
    """Evaluate every rule against the metrics snapshot for one
    fund-quarter. Per-CIK overrides are applied at rule-lookup time.
    Rules with `scope=issuer` or `scope=sector` emit one Breach per
    scope key that trips the threshold."""
    breaches: list[Breach] = []
    for rule in config.rules:
        effective = _rule_for_fund(rule, fund_cik, config.overrides)
        if rule.metric == "hhi":
            _emit(breaches, effective, fund_cik, quarter, hhi_value, None)
        elif rule.metric == "effective_n":
            _emit(breaches, effective, fund_cik, quarter, effective_n_value, None)
        elif rule.metric == "top_n_weight":
            n = int(effective.params.get("n", 10))
            observed = top_n_weight(weights, n)
            _emit(breaches, effective, fund_cik, quarter, observed, f"top{n}")
        elif rule.metric == "issuer_weight":
            for issuer, weight in issuer_wts.items():
                _emit(breaches, effective, fund_cik, quarter, float(weight), str(issuer))
        elif rule.metric == "sector_weight":
            excluded = set(effective.exclude)
            for sector, weight in sector_wts.items():
                key = str(sector)
                if key in excluded:
                    continue
                _emit(breaches, effective, fund_cik, quarter, float(weight), key)
        # unknown metrics are skipped silently — reserved for future use
    return breaches
