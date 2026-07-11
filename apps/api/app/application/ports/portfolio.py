"""Ports owned by the portfolio-planning application service."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from app.domain.portfolio.model import (
    CandidateAction,
    CandidateOffer,
    FailureRiskSignal,
    LPTBSignal,
    PriceSignal,
)


class PriceForecastService(Protocol):
    def forecast(self, offer: CandidateOffer, history_cents: tuple[int, ...]) -> PriceSignal: ...


class FailureRiskService(Protocol):
    def estimate(self, offer: CandidateOffer) -> FailureRiskSignal: ...


class LPTBService(Protocol):
    def calculate(self, offer: CandidateOffer, deadline: date) -> LPTBSignal: ...


class PortfolioOptimizer(Protocol):
    def optimize(self, actions: tuple[CandidateAction, ...]) -> object: ...
