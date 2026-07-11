"""Contract-owned need specifications for the portfolio planner."""

from __future__ import annotations

from math import ceil

from .model import NeedSpec


def party_needs(
    participants: int,
    *,
    include_candles: bool = True,
    candle_quantity: int = 1,
) -> tuple[NeedSpec, ...]:
    """Create the deterministic initial ProblemDefinition for a party mission.

    The result is persisted in the mission contract. The planner never reads
    this template directly, so later intent adapters can supply other needs.
    """

    count = max(1, participants)
    needs = (
        NeedSpec("snacks", "snacks", max(1, ceil(count / 4))),
        NeedSpec("drinks_juice", "drinks", max(1, ceil(count * 0.4)), ("juice",)),
        NeedSpec("drinks_water", "drinks", max(1, ceil(count * 0.3)), ("water",)),
        NeedSpec("cake", "cake", 1),
        NeedSpec("balloons", "decorations", 1, ("balloons",)),
        NeedSpec("banner", "decorations", 1, ("banner",)),
        NeedSpec("plates", "tableware", 1, ("plates",)),
        NeedSpec("cups", "tableware", 1, ("cups",)),
        NeedSpec("napkins", "napkins", 1, ("napkins",)),
    )
    if include_candles:
        return (
            *needs,
            NeedSpec(
                "candles",
                "candles",
                max(1, candle_quantity),
                ("candles",),
            ),
        )
    return needs


def needs_to_payload(needs: tuple[NeedSpec, ...]) -> list[dict[str, object]]:
    return [
        {
            "id": need.id,
            "category": need.category,
            "quantity": need.quantity,
            "required_tags": list(need.required_tags),
            "must": need.must,
        }
        for need in needs
    ]


def needs_from_payload(value: object) -> tuple[NeedSpec, ...]:
    if not isinstance(value, list):
        return ()
    needs: list[NeedSpec] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            needs.append(
                NeedSpec(
                    id=str(item["id"]),
                    category=str(item["category"]),
                    quantity=int(item["quantity"]),
                    required_tags=tuple(str(tag) for tag in item.get("required_tags", [])),
                    must=bool(item.get("must", True)),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(needs)
