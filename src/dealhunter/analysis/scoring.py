"""
Deterministic, unit-tested scoring. Claude supplies the qualitative inputs
(analysis.py); everything here is a plain function of those inputs so the
math is auditable and can be sanity-checked (and unit tested) independent of
any live API call.
"""
from __future__ import annotations

from dealhunter.models import AnalysisResult, DemandTier, LiquidityAssessment, RiskLevel

_TIER_ORDER = {DemandTier.LOW: 0, DemandTier.MEDIUM: 1, DemandTier.HIGH: 2}

_AUTHENTICITY_RISK_CAP = {
    RiskLevel.HIGH: 30,
    RiskLevel.MEDIUM: 60,
}


def compute_discount(all_in_price: float | None, estimated_value: float | None) -> float | None:
    """Fraction below estimated value, e.g. 0.35 = 35% under market.
    None if we don't have both a price and a positive valuation to compare."""
    if all_in_price is None or estimated_value is None or estimated_value <= 0:
        return None
    return (estimated_value - all_in_price) / estimated_value


def compute_deal_score(
    all_in_price: float | None,
    analysis: AnalysisResult,
) -> tuple[int, float | None]:
    """Returns (deal_score, discount fraction or None).

    deal_score is simply the discount expressed as a percent: 35% under
    estimated value scores 35, 10% over market scores -10. No confidence
    dampening - Claude's confidence is shown alongside the score in the UI
    as context, not baked into the number itself, so the score always means
    exactly what it says.

    A high or medium authenticity risk caps the score outright, regardless
    of price - a steep discount on a probably-fake item is not a good deal.
    """
    discount = compute_discount(all_in_price, analysis.estimated_value)
    if discount is None:
        return 0, None

    score = round(discount * 100)

    cap = _AUTHENTICITY_RISK_CAP.get(analysis.authenticity_risk)
    if cap is not None:
        score = min(score, cap)

    return score, discount


def compute_liquidity(
    comparable_count: int,
    analysis: AnalysisResult,
    high_threshold: int = 5,
    medium_threshold: int = 2,
) -> LiquidityAssessment:
    """Combines an algorithmic signal (how many comparable items have shown
    up recently) with Claude's qualitative brand/demand read, taking the
    more conservative (lower) of the two tiers."""
    if comparable_count >= high_threshold:
        algorithmic_tier = DemandTier.HIGH
    elif comparable_count >= medium_threshold:
        algorithmic_tier = DemandTier.MEDIUM
    else:
        algorithmic_tier = DemandTier.LOW

    claude_tier = analysis.demand_tier
    final_tier = min(algorithmic_tier, claude_tier, key=lambda t: _TIER_ORDER[t])

    reasoning = (
        f"Algorithmic signal: {comparable_count} comparable listing(s) seen "
        f"in the lookback window -> {algorithmic_tier.value}. "
        f"Claude's qualitative read: {claude_tier.value} "
        f"({analysis.demand_reasoning}). "
        f"Final rating uses the more conservative of the two: {final_tier.value}."
    )

    return LiquidityAssessment(
        rating=final_tier,
        comparable_count=comparable_count,
        algorithmic_tier=algorithmic_tier,
        claude_tier=claude_tier,
        reasoning=reasoning,
    )


def qualifies_for_notification(
    analysis: AnalysisResult,
    discount: float | None,
    discount_threshold: float | None,
) -> bool:
    if not analysis.matches_criteria:
        return False
    if discount_threshold is None:
        # No minimum discount configured for this hunt - any match qualifies.
        return True
    if discount is None:
        return False
    return discount >= discount_threshold
