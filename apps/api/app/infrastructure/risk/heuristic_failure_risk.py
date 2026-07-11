"""Explainable availability and delivery-risk estimator."""

from __future__ import annotations

from app.domain.portfolio.model import CandidateOffer, FailureRiskSignal


class HeuristicFailureRiskModel:
    def estimate(self, offer: CandidateOffer) -> FailureRiskSignal:
        stock_component = 0.55 if offer.stock <= 1 else 0.25 if offer.stock <= 5 else 0.05
        delivery_component = (1 - offer.delivery_success_rate) * 0.45
        merchant_component = (1 - offer.merchant_reliability) * 0.25
        unavailable_component = 0.80 if not offer.available else 0.0
        probability = min(0.99, stock_component + delivery_component + merchant_component + unavailable_component)
        return FailureRiskSignal(
            probability=round(probability, 4),
            reason=(
                f"stock={offer.stock}; delivery_success={offer.delivery_success_rate:.2f}; "
                f"merchant_reliability={offer.merchant_reliability:.2f}"
            ),
        )
