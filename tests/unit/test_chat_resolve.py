from concrisk.chat import AmbiguousFund, ResolvedFund, UnknownFund, resolve_fund_ref

# Fixture funds mimicking config/funds.yaml — kept small and deterministic
# so we don't depend on the real YAML for unit tests.
FUNDS = [
    ("0001067983", "Berkshire Hathaway"),
    ("0001350694", "Bridgewater Associates"),
    ("0001037389", "Renaissance Technologies"),
    ("0001603466", "Point72 Asset Management"),
    ("0001336528", "Pershing Square Capital Management"),
    ("0001167483", "Tiger Global Management"),
]


def test_exact_cik_matches_with_any_padding() -> None:
    for ref in ("1067983", "0001067983", "00001067983"):
        r = resolve_fund_ref(ref, FUNDS)
        assert isinstance(r, ResolvedFund)
        assert r.cik == "0001067983"


def test_exact_cik_no_match_returns_unknown_when_no_name_fallback() -> None:
    r = resolve_fund_ref("9999999", FUNDS)
    assert isinstance(r, UnknownFund)


def test_exact_name_match_case_insensitive() -> None:
    r = resolve_fund_ref("berkshire hathaway", FUNDS)
    assert isinstance(r, ResolvedFund)
    assert r.name == "Berkshire Hathaway"


def test_substring_unique_match() -> None:
    r = resolve_fund_ref("Berkshire", FUNDS)
    assert isinstance(r, ResolvedFund)
    assert r.name == "Berkshire Hathaway"


def test_substring_ambiguous_returns_candidates() -> None:
    # 'Management' appears in Point72, Pershing Square, Tiger Global
    r = resolve_fund_ref("Management", FUNDS)
    assert isinstance(r, AmbiguousFund)
    names = {c.name for c in r.candidates}
    assert {"Point72 Asset Management", "Tiger Global Management"} <= names


def test_fuzzy_match_on_typo() -> None:
    r = resolve_fund_ref("Renaisance Techologies", FUNDS)  # two typos
    assert isinstance(r, ResolvedFund)
    assert r.name == "Renaissance Technologies"


def test_unknown_returns_unknown_fund() -> None:
    assert isinstance(resolve_fund_ref("nonsuchfund", FUNDS), UnknownFund)


def test_empty_string_returns_unknown() -> None:
    assert isinstance(resolve_fund_ref("", FUNDS), UnknownFund)
    assert isinstance(resolve_fund_ref("   ", FUNDS), UnknownFund)


def test_reads_real_config_by_default() -> None:
    # Sanity check that the default read hits the real YAML shipped in the repo.
    r = resolve_fund_ref("Berkshire")
    assert isinstance(r, ResolvedFund)
    assert r.cik == "0001067983"
