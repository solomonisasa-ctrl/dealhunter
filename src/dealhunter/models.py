"""
Shared data types. These are the contract between sources, analysis, storage,
and the dashboard - every module below imports from here rather than passing
around raw dicts, so a field rename is a one-file change.
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ListingStatus(str, Enum):
    ACTIVE = "active"
    SOLD = "sold"
    UNKNOWN = "unknown"


class RiskLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DemandTier(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class WatchItem(BaseModel):
    id: str
    category: str
    description: str
    discount_threshold: float = 0.30
    lookback_days: int = 30
    enabled: bool = True
    parsed_criteria: Optional[dict[str, Any]] = None


class Listing(BaseModel):
    """A normalized listing, regardless of which source it came from."""

    id: str  # globally unique, e.g. "reddit:abc123" or "ebay:v1|1234567890"
    source: str  # "reddit" | "ebay" | "etsy"
    category: str
    title: str
    url: str
    price: Optional[float] = None
    shipping_price: Optional[float] = None
    currency: str = "USD"
    image_url: Optional[str] = None
    body: str = ""  # description / post text used for analysis
    posted_at: Optional[float] = None  # unix timestamp
    status: ListingStatus = ListingStatus.UNKNOWN
    raw: dict[str, Any] = Field(default_factory=dict)  # source-specific extras

    @property
    def all_in_price(self) -> Optional[float]:
        if self.price is None:
            return None
        return self.price + (self.shipping_price or 0.0)


class AnalysisResult(BaseModel):
    """Raw output of the Claude analyzer call for one listing."""

    matches_criteria: bool
    match_reasoning: str
    estimated_value: Optional[float]
    confidence: float  # 0-1, Claude's self-reported confidence in estimated_value
    condition_summary: str
    authenticity_risk: RiskLevel
    authenticity_notes: str
    rarity_notes: str
    demand_tier: DemandTier
    demand_reasoning: str


class LiquidityAssessment(BaseModel):
    rating: DemandTier
    comparable_count: int
    algorithmic_tier: DemandTier
    claude_tier: DemandTier
    reasoning: str


class Finding(BaseModel):
    """A fully-scored listing, ready for storage/notification/dashboard display."""

    id: str  # f"{watch_item_id}:{listing.id}" - a listing can match >1 watch item
    listing: Listing
    watch_item_id: str
    analysis: AnalysisResult
    deal_score: int  # 0-100
    liquidity: LiquidityAssessment
    all_in_price: Optional[float]
    discount: Optional[float]  # fraction, e.g. 0.35 = 35% under estimated value
    notified: bool = False
    duplicate_of: Optional[str] = None  # id of an earlier Finding for the same physical item
    created_at: float = Field(default_factory=time.time)

    @property
    def score_color(self) -> str:
        if self.deal_score >= 80:
            return "green"
        if self.deal_score >= 50:
            return "yellow"
        return "red"


class SourceHealth(BaseModel):
    status: str = "ok"  # "ok" | "warning" | "error"
    fetched: int = 0
    new: int = 0
    errors: list[str] = Field(default_factory=list)


class HealthReport(BaseModel):
    timestamp: float = Field(default_factory=time.time)
    overall_status: str = "ok"  # "ok" | "warning" | "error"
    duration_seconds: float = 0.0
    sources: dict[str, SourceHealth] = Field(default_factory=dict)
    findings_count: int = 0
    error_message: Optional[str] = None
