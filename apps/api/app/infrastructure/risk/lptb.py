"""Latest-point-to-buy calculation per need and offer."""

from __future__ import annotations

from datetime import date, timedelta

from app.domain.portfolio.model import CandidateOffer, LPTBSignal


class LPTBCalculator:
    def __init__(self, *, safety_buffer_days: int = 1) -> None:
        if safety_buffer_days < 0:
            raise ValueError("Safety buffer cannot be negative")
        self.safety_buffer_days = safety_buffer_days

    def calculate(self, offer: CandidateOffer, deadline: date) -> LPTBSignal:
        lptb = deadline - timedelta(
            days=offer.p95_delivery_days + self.safety_buffer_days
        )
        return LPTBSignal(
            lptb=lptb,
            p95_delivery_days=offer.p95_delivery_days,
            safety_buffer_days=self.safety_buffer_days,
            reason=(
                f"deadline - {offer.p95_delivery_days} p95 delivery days "
                f"- {self.safety_buffer_days} safety buffer days"
            ),
        )
