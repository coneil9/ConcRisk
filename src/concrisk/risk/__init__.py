"""Risk engine: pure DataFrame-in, DataFrame/dataclass-out functions.

Per SPEC §3 layering rule, nothing in this package touches the DB or
network. Services and API wire real data through these functions.
"""

from concrisk.risk.concentration import (
    UNCLASSIFIED,
    effective_n,
    hhi,
    issuer_weights,
    largest_issuer_weight,
    sector_weights,
    top_n_weight,
)
from concrisk.risk.issuers import (
    add_issuer_key,
    load_issuer_map,
    resolve_issuer_key,
)
from concrisk.risk.limits import (
    Breach,
    LimitsConfig,
    Rule,
    evaluate_limits,
    load_limits,
)
from concrisk.risk.weights import compute_weights

__all__ = [
    "UNCLASSIFIED",
    "Breach",
    "LimitsConfig",
    "Rule",
    "add_issuer_key",
    "compute_weights",
    "effective_n",
    "evaluate_limits",
    "hhi",
    "issuer_weights",
    "largest_issuer_weight",
    "load_issuer_map",
    "load_limits",
    "resolve_issuer_key",
    "sector_weights",
    "top_n_weight",
]
