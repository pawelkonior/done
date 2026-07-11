from app.domain.portfolio.needs import party_needs


def test_party_needs_include_candles_by_default() -> None:
    needs = party_needs(10)

    assert len(needs) == 10
    assert needs[-1].id == "candles"
    assert needs[-1].category == "candles"
    assert needs[-1].required_tags == ("candles",)


def test_party_needs_can_omit_candles_without_changing_other_needs() -> None:
    with_candles = party_needs(10)
    without_candles = party_needs(10, include_candles=False)

    assert without_candles == tuple(
        need for need in with_candles if need.id != "candles"
    )
    assert all(need.id != "candles" for need in without_candles)


def test_party_needs_scale_an_explicit_candle_requirement() -> None:
    needs = party_needs(10, include_candles=True, candle_quantity=2)

    candles = next(need for need in needs if need.id == "candles")
    assert candles.quantity == 2
