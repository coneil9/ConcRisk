import difflib
from dataclasses import dataclass

from concrisk.services import list_tracked_funds

_FUZZY_CUTOFF = 0.6
_MAX_CANDIDATES = 5


@dataclass(frozen=True)
class ResolvedFund:
    cik: str
    name: str


@dataclass(frozen=True)
class AmbiguousFund:
    candidates: list[ResolvedFund]


@dataclass(frozen=True)
class UnknownFund:
    pass


ResolveResult = ResolvedFund | AmbiguousFund | UnknownFund


def resolve_fund_ref(
    ref: str,
    funds: list[tuple[str, str]] | None = None,
) -> ResolveResult:
    """Resolve a user-supplied fund reference (CIK or name) to one tracked fund.

    - Exact CIK match (any padding) → ResolvedFund
    - Exact case-insensitive name match → ResolvedFund
    - Substring match on name → ResolvedFund if unique, AmbiguousFund if multiple
    - difflib close-match (cutoff 0.6, top 5) → same rule
    - Otherwise → UnknownFund

    `funds` argument is for tests; production reads from config/funds.yaml.
    """
    tracked = funds if funds is not None else list_tracked_funds()
    if not ref or not ref.strip():
        return UnknownFund()
    ref_stripped = ref.strip()

    # 1. Exact CIK (int-normalized)
    try:
        needle_int = int(ref_stripped)
        for cik, name in tracked:
            if int(cik) == needle_int:
                return ResolvedFund(cik=cik, name=name)
    except ValueError:
        pass

    ref_upper = ref_stripped.upper()

    # 2. Exact name (case-insensitive)
    for cik, name in tracked:
        if name.upper() == ref_upper:
            return ResolvedFund(cik=cik, name=name)

    # 3. Substring on name
    substr_hits = [(cik, name) for cik, name in tracked if ref_upper in name.upper()]
    if len(substr_hits) == 1:
        cik, name = substr_hits[0]
        return ResolvedFund(cik=cik, name=name)
    if substr_hits:
        return AmbiguousFund(
            candidates=[ResolvedFund(cik=c, name=n) for c, n in substr_hits[:_MAX_CANDIDATES]]
        )

    # 4. difflib fuzzy match
    name_to_cik = {name: cik for cik, name in tracked}
    close = difflib.get_close_matches(
        ref_stripped, list(name_to_cik.keys()), n=_MAX_CANDIDATES, cutoff=_FUZZY_CUTOFF
    )
    if len(close) == 1:
        name = close[0]
        return ResolvedFund(cik=name_to_cik[name], name=name)
    if close:
        return AmbiguousFund(
            candidates=[ResolvedFund(cik=name_to_cik[n], name=n) for n in close]
        )

    return UnknownFund()
