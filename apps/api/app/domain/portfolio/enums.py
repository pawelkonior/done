"""Stable enums shared by portfolio planning adapters and read models."""

from __future__ import annotations

from enum import StrEnum


class ActionKind(StrEnum):
    BUY_NOW = "buy_now"
    WAIT = "wait"


class PriceSignalKind(StrEnum):
    BUY_NOW_PREFERRED = "buy_now_preferred"
    WAIT_PREFERRED = "wait_preferred"
    NEUTRAL = "neutral"


class TimingMode(StrEnum):
    NORMAL = "normal"
    ORANGE = "orange"


class PortfolioDecisionStatus(StrEnum):
    FEASIBLE = "feasible"
    WAITING = "waiting"
    INFEASIBLE_PLAN = "infeasible_plan"
    VALIDATION_ERROR = "validation_error"
    INTERNAL_VALIDATION_ERROR = "internal_validation_error"


class PortfolioTrigger(StrEnum):
    MISSION_CREATED = "mission_created"
    CONTRACT_REVISED = "contract_revised"
    MANUAL_REPLAN = "manual_replan"
    DAILY = "daily"
    PRICE_CHANGED = "price_changed"
    STOCK_CHANGED = "stock_changed"
    DELIVERY_CHANGED = "delivery_changed"
