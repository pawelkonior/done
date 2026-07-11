"""A conservative, data-honest price forecast for the first portfolio release."""

from __future__ import annotations

from app.domain.portfolio.enums import PriceSignalKind
from app.domain.portfolio.model import CandidateOffer, PriceSignal

from .conformal_calibrator import ConformalCalibrator


class HeuristicPriceForecaster:
    """Uses only stored observations and makes uncertainty explicit.

    This adapter is intentionally replaceable: it allows the system to collect
    price history before a trained model or conformal calibrator is introduced.
    """

    def __init__(self, calibrator: ConformalCalibrator | None = None) -> None:
        self.calibrator = calibrator or ConformalCalibrator()

    def forecast(self, offer: CandidateOffer, history_cents: tuple[int, ...]) -> PriceSignal:
        current = offer.price_cents
        if len(history_cents) < 2:
            lower, upper = self.calibrator.interval(current, history_cents)
            return PriceSignal(
                kind=PriceSignalKind.BUY_NOW_PREFERRED,
                expected_price_cents=current,
                lower_cents=lower,
                upper_cents=upper,
                confidence=0.35,
                reason="Insufficient price history; the conservative default avoids waiting.",
            )

        recent = history_cents[-5:]
        average = round(sum(recent) / len(recent))
        previous = recent[-2]
        trend = current - previous
        if current <= average or trend > 0:
            expected = max(current, average)
            lower, upper = self.calibrator.interval(expected, recent)
            return PriceSignal(
                kind=PriceSignalKind.BUY_NOW_PREFERRED,
                expected_price_cents=expected,
                lower_cents=lower,
                upper_cents=upper,
                confidence=0.65,
                reason="Current price is at or below its recent level, or the recent trend is rising.",
            )
        lower, upper = self.calibrator.interval(average, recent)
        return PriceSignal(
            kind=PriceSignalKind.WAIT_PREFERRED,
            expected_price_cents=average,
            lower_cents=lower,
            upper_cents=upper,
            confidence=0.60,
            reason="Current price is above the recent average and the short trend is not rising.",
        )
