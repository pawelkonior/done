"""Conservative interval calibration for the heuristic forecast adapter."""

from __future__ import annotations


class ConformalCalibrator:
    """Derives an empirical uncertainty band without pretending to train a model."""

    def interval(self, center_cents: int, observations: tuple[int, ...]) -> tuple[int, int]:
        if len(observations) < 2:
            margin = max(1, round(center_cents * 0.10))
            return max(0, center_cents - margin), center_cents + margin
        residuals = sorted(abs(observation - center_cents) for observation in observations[-20:])
        percentile_index = min(len(residuals) - 1, round((len(residuals) - 1) * 0.9))
        margin = max(1, residuals[percentile_index])
        return max(0, center_cents - margin), center_cents + margin
