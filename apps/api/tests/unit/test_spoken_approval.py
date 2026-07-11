from __future__ import annotations

import pytest

from app.workflow import WorkflowConflictError, require_spoken_approval


def test_spoken_approval_accepts_polish_words_and_visible_merchant_name() -> None:
    transcript = (
        "Tak, zatwierdzam sto dziewięćdziesiąt dwa złote "
        "siedemdziesiąt trzy grosze w Party Market."
    )

    assert require_spoken_approval(
        transcript,
        amount_cents=19_273,
        currency="PLN",
        merchant_id="merchant-b",
        merchant_labels=("Party Market",),
    ) == transcript


def test_spoken_approval_accepts_spoken_technical_merchant_id() -> None:
    transcript = "Tak, potwierdzam 192,73 PLN u merchant B."

    assert require_spoken_approval(
        transcript,
        amount_cents=19_273,
        currency="PLN",
        merchant_id="merchant-b",
    ) == transcript


@pytest.mark.parametrize(
    "transcript",
    [
        "Nie zatwierdzam 192,73 PLN w Party Market.",
        "Tak, zatwierdzam 190 PLN w Party Market.",
        "Tak, zatwierdzam 192,73 PLN w innym sklepie.",
    ],
)
def test_spoken_approval_rejects_negative_or_mismatched_evidence(
    transcript: str,
) -> None:
    with pytest.raises(WorkflowConflictError):
        require_spoken_approval(
            transcript,
            amount_cents=19_273,
            currency="PLN",
            merchant_id="merchant-b",
            merchant_labels=("Party Market",),
        )
