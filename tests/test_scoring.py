from dealhunter.analysis.scoring import (
    compute_deal_score,
    compute_discount,
    compute_liquidity,
    qualifies_for_notification,
)
from dealhunter.models import AnalysisResult, DemandTier, RiskLevel


def make_analysis(**overrides) -> AnalysisResult:
    defaults = dict(
        matches_criteria=True,
        match_reasoning="matches",
        estimated_value=1000.0,
        confidence=1.0,
        condition_summary="good",
        authenticity_risk=RiskLevel.NONE,
        authenticity_notes="none",
        rarity_notes="common",
        demand_tier=DemandTier.MEDIUM,
        demand_reasoning="steady demand",
    )
    defaults.update(overrides)
    return AnalysisResult(**defaults)


def test_discount_no_price_or_value_is_none():
    assert compute_discount(None, 1000.0) is None
    assert compute_discount(500.0, None) is None
    assert compute_discount(500.0, 0) is None


def test_discount_basic_math():
    assert compute_discount(700.0, 1000.0) == 0.3


def test_deal_score_is_zero_at_zero_discount():
    analysis = make_analysis(estimated_value=1000.0, confidence=1.0)
    score, discount = compute_deal_score(1000.0, analysis)
    assert discount == 0.0
    assert score == 0


def test_deal_score_equals_discount_percent():
    analysis = make_analysis(estimated_value=1000.0, confidence=1.0)
    score, discount = compute_deal_score(600.0, analysis)  # 40% under value
    assert discount == 0.4
    assert score == 40


def test_deal_score_ignores_confidence():
    analysis = make_analysis(estimated_value=1000.0, confidence=0.1)
    score, _ = compute_deal_score(600.0, analysis)  # same 40% discount, low confidence
    # confidence no longer dampens the score - it's shown separately in the UI as context.
    assert score == 40


def test_deal_score_overpriced_goes_negative():
    analysis = make_analysis(estimated_value=1000.0, confidence=1.0)
    score, discount = compute_deal_score(1500.0, analysis)  # 50% over value
    assert discount == -0.5
    assert score == -50


def test_deal_score_none_without_valuation():
    analysis = make_analysis(estimated_value=None)
    score, discount = compute_deal_score(600.0, analysis)
    assert score == 0
    assert discount is None


def test_high_authenticity_risk_caps_score():
    analysis = make_analysis(
        estimated_value=1000.0, confidence=1.0, authenticity_risk=RiskLevel.HIGH
    )
    score, discount = compute_deal_score(300.0, analysis)  # huge, suspicious discount
    assert discount == 0.7
    assert score == 30  # capped despite the steep discount


def test_medium_authenticity_risk_caps_score():
    analysis = make_analysis(
        estimated_value=1000.0, confidence=1.0, authenticity_risk=RiskLevel.MEDIUM
    )
    score, _ = compute_deal_score(300.0, analysis)
    assert score == 60


def test_liquidity_takes_the_more_conservative_tier():
    analysis = make_analysis(demand_tier=DemandTier.HIGH)
    result = compute_liquidity(comparable_count=0, analysis=analysis)
    assert result.algorithmic_tier == DemandTier.LOW
    assert result.claude_tier == DemandTier.HIGH
    assert result.rating == DemandTier.LOW

    result2 = compute_liquidity(comparable_count=10, analysis=analysis)
    assert result2.algorithmic_tier == DemandTier.HIGH
    assert result2.rating == DemandTier.HIGH


def test_liquidity_thresholds():
    analysis = make_analysis(demand_tier=DemandTier.HIGH)
    assert compute_liquidity(1, analysis).algorithmic_tier == DemandTier.LOW
    assert compute_liquidity(2, analysis).algorithmic_tier == DemandTier.MEDIUM
    assert compute_liquidity(4, analysis).algorithmic_tier == DemandTier.MEDIUM
    assert compute_liquidity(5, analysis).algorithmic_tier == DemandTier.HIGH


def test_qualifies_for_notification_requires_match_and_threshold():
    analysis = make_analysis(matches_criteria=True)
    assert qualifies_for_notification(analysis, 0.35, 0.30) is True
    assert qualifies_for_notification(analysis, 0.25, 0.30) is False
    assert qualifies_for_notification(analysis, None, 0.30) is False

    non_match = make_analysis(matches_criteria=False)
    assert qualifies_for_notification(non_match, 0.9, 0.30) is False


def test_qualifies_for_notification_no_threshold_means_any_match_qualifies():
    analysis = make_analysis(matches_criteria=True)
    assert qualifies_for_notification(analysis, 0.35, None) is True
    assert qualifies_for_notification(analysis, -0.5, None) is True  # even overpriced
    assert qualifies_for_notification(analysis, None, None) is True  # even no valuation

    non_match = make_analysis(matches_criteria=False)
    assert qualifies_for_notification(non_match, 0.9, None) is False
