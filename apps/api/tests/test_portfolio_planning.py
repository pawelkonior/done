from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import PortfolioShadowSettings
from app.domain.portfolio.enums import PortfolioTrigger, PriceSignalKind, TimingMode
from app.domain.portfolio.model import (
    CandidateOffer,
    FailureRiskSignal,
    LPTBSignal,
    NeedSpec,
    PriceSignal,
)
from app.domain.portfolio.policies import TimingGate
from app.main import create_app
from app.domain.mission.catalog import CatalogPlanningAgent, PlannedCatalogLine


def _create(client: TestClient, transcript: str) -> dict:
    response = client.post(
        "/v1/missions/text",
        json={"transcript": transcript, "locale": "pl-PL", "timezone": "Europe/Warsaw"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_timing_gate_removes_wait_only_for_an_orange_offer() -> None:
    offer = CandidateOffer(
        id="ofs-1",
        snapshot_id="mkt-1",
        product_id="product-1",
        merchant_id="merchant-1",
        category="snacks",
        price_cents=599,
        currency="PLN",
        stock=12,
        rating=4.8,
        merchant_reliability=0.95,
        delivery_success_rate=0.95,
        p95_delivery_days=1,
        nut_free=True,
    )
    actions = TimingGate().build_actions(
        need=NeedSpec("snacks", "snacks", 1),
        offer=offer,
        price=PriceSignal(
            kind=PriceSignalKind.WAIT_PREFERRED,
            expected_price_cents=549,
            lower_cents=500,
            upper_cents=600,
            confidence=0.7,
            reason="test",
        ),
        risk=FailureRiskSignal(0.1, "test"),
        lptb=LPTBSignal(date(2026, 7, 11), 1, 1, "test"),
        today=date(2026, 7, 11),
    )

    assert len(actions) == 1
    assert actions[0].timing_mode is TimingMode.ORANGE
    assert actions[0].action.value == "buy_now"


def test_created_mission_contains_a_persisted_portfolio_decision(
    client: TestClient, transcript: str
) -> None:
    created = _create(client, transcript)

    decision = created["portfolio_decision"]
    assert created["mission"]["status"] == "approval_required"
    assert decision["status"] == "feasible"
    assert decision["selected_merchant_id"] == "merchant-b"
    # The transcript says ten children (count), not ten-year-olds (age), so
    # candles must not be inferred as a purchase need.
    assert len(decision["actions"]) == 9
    assert all(action["need_id"] != "candles" for action in decision["actions"])
    assert all(action["action"] == "buy_now" for action in decision["actions"])
    assert all(action["lptb"] for action in decision["actions"])
    assert all(action["quantity"] > 0 for action in decision["actions"])
    assert sorted(
        (action["product_id"], action["quantity"]) for action in decision["actions"]
    ) == sorted(
        (item["product_id"], item["quantity"])
        for item in created["basket"]["items"]
    )
    assert created["approval"]["decision_id"] == decision["id"]


def test_replan_creates_new_decision_and_supersedes_approval(
    client: TestClient, transcript: str
) -> None:
    created = _create(client, transcript)
    mission_id = created["mission"]["id"]
    revision = created["mission"]["revision"]
    first_approval_id = created["approval"]["id"]
    first_decision_id = created["portfolio_decision"]["id"]

    replanned = client.post(
        f"/v1/missions/{mission_id}/replan",
        json={"expected_revision": revision},
    )
    assert replanned.status_code == 200, replanned.text
    detail = replanned.json()

    assert detail["mission"]["revision"] == revision + 1
    assert detail["approval"]["id"] != first_approval_id
    assert detail["portfolio_decision"]["id"] != first_decision_id
    assert detail["approval"]["decision_id"] == detail["portfolio_decision"]["id"]
    assert "approval.superseded" in [event["type"] for event in detail["events"]]
    assert "portfolio.replanned" in [event["type"] for event in detail["events"]]

    history = client.get(f"/v1/missions/{mission_id}/portfolio-decisions")
    assert history.status_code == 200
    assert history.json()["total"] == 2


def test_deadline_excludes_offers_whose_p95_delivery_is_too_late(
    client: TestClient, transcript: str
) -> None:
    with client.app.state.database.transaction() as connection:
        connection.execute(
            "UPDATE merchants SET delivery_success_rate = 0.80 WHERE id = 'merchant-b'"
        )

    created = _create(client, transcript)

    assert created["mission"]["status"] == "failed"
    assert created["portfolio_decision"]["status"] == "infeasible_plan"
    assert created["basket"] is None
    assert created["approval"] is None
    assert "No eligible offers" in " ".join(
        created["portfolio_decision"]["constraint_report"]
    )


def test_delivery_option_must_use_the_checkout_merchant(
    client: TestClient, transcript: str
) -> None:
    created = _create(client, transcript)
    mission_id = created["mission"]["id"]
    replacement = next(option for option in created["delivery_options"] if not option["selected"])

    with client.app.state.database.transaction() as connection:
        basket = connection.execute(
            "SELECT merchant_id FROM baskets WHERE mission_id = ?", (mission_id,)
        ).fetchone()
        delivery_merchants = connection.execute(
            "SELECT DISTINCT merchant_id FROM delivery_options WHERE mission_id = ?", (mission_id,)
        ).fetchall()
        assert basket is not None
        assert {row["merchant_id"] for row in delivery_merchants} == {basket["merchant_id"]}
        connection.execute(
            "UPDATE delivery_options SET merchant_id = 'merchant-c' WHERE id = ?",
            (replacement["id"],),
        )

    response = client.put(
        f"/v1/missions/{mission_id}/delivery-option",
        json={
            "delivery_option_id": replacement["id"],
            "expected_revision": created["mission"]["revision"],
        },
    )

    assert response.status_code == 409
    assert "not compatible" in response.json()["message"]


def test_replan_retry_reuses_the_current_decision(
    client: TestClient, transcript: str
) -> None:
    created = _create(client, transcript)
    mission_id = created["mission"]["id"]

    first = client.post(f"/v1/missions/{mission_id}/replan", json={})
    assert first.status_code == 200, first.text
    first_detail = first.json()

    retry = client.post(f"/v1/missions/{mission_id}/replan", json={})
    assert retry.status_code == 200, retry.text
    retry_detail = retry.json()

    assert retry_detail["mission"]["revision"] == first_detail["mission"]["revision"]
    assert retry_detail["portfolio_decision"]["id"] == first_detail["portfolio_decision"]["id"]
    assert retry_detail["approval"]["id"] == first_detail["approval"]["id"]
    history = client.get(f"/v1/missions/{mission_id}/portfolio-decisions")
    assert history.status_code == 200
    assert history.json()["total"] == 2


def test_planner_replays_a_persisted_idempotency_key(
    client: TestClient, transcript: str
) -> None:
    created = _create(client, transcript)
    mission_id = created["mission"]["id"]
    planner = client.app.state.portfolio_planner
    now = datetime.now(UTC)

    with client.app.state.database.transaction() as connection:
        first = planner.run(
            connection,
            mission_id=mission_id,
            trigger=PortfolioTrigger.MANUAL_REPLAN,
            now=now,
        )
        replayed = planner.run(
            connection,
            mission_id=mission_id,
            trigger=PortfolioTrigger.MANUAL_REPLAN,
            now=now,
        )
        decision_count = connection.execute(
            "SELECT COUNT(*) AS count FROM portfolio_decisions WHERE mission_id = ?",
            (mission_id,),
        ).fetchone()["count"]

    assert replayed.id == first.id
    assert replayed.snapshot_id == first.snapshot_id
    assert [action.need_id for action in replayed.selected_actions] == [
        action.need_id for action in first.selected_actions
    ]
    assert decision_count == 2


def test_catalog_change_invalidates_replan_reuse(client: TestClient, transcript: str) -> None:
    created = _create(client, transcript)
    mission_id = created["mission"]["id"]

    first = client.post(f"/v1/missions/{mission_id}/replan", json={})
    assert first.status_code == 200, first.text
    first_detail = first.json()
    with client.app.state.database.transaction() as connection:
        connection.execute(
            "UPDATE products SET price_cents = price_cents + 100 WHERE id = 'snack-pretzels'"
        )

    changed = client.post(f"/v1/missions/{mission_id}/replan", json={})
    assert changed.status_code == 200, changed.text
    changed_detail = changed.json()

    assert changed_detail["mission"]["revision"] == first_detail["mission"]["revision"] + 1
    assert changed_detail["portfolio_decision"]["id"] != first_detail["portfolio_decision"]["id"]
    history = client.get(f"/v1/missions/{mission_id}/portfolio-decisions")
    assert history.status_code == 200
    assert history.json()["total"] == 3


def test_contract_owns_needs_and_revises_them_with_participant_count(
    client: TestClient, transcript: str
) -> None:
    created = _create(client, transcript)
    mission_id = created["mission"]["id"]
    initial_needs = {need["id"]: need["quantity"] for need in created["contract"]["needs"]}
    assert "candles" not in initial_needs
    assert initial_needs["snacks"] == 3
    assert initial_needs["drinks_juice"] == 4
    assert initial_needs["drinks_water"] == 3

    corrected = client.post(
        f"/v1/missions/{mission_id}/corrections",
        json={
            "correction": "Change the party to 20 children",
            "expected_revision": created["mission"]["revision"],
        },
    )
    assert corrected.status_code == 200, corrected.text
    detail = corrected.json()
    revised_needs = {need["id"]: need["quantity"] for need in detail["contract"]["needs"]}

    assert revised_needs["snacks"] == 5
    assert revised_needs["drinks_juice"] == 8
    assert revised_needs["drinks_water"] == 6
    assert detail["approval"]["decision_id"] == detail["portfolio_decision"]["id"]


def test_shadow_mode_records_comparison_without_touching_checkout_state(
    tmp_path: Path, transcript: str
) -> None:
    app = create_app(
        tmp_path / "shadow.sqlite3",
        portfolio_shadow_settings=PortfolioShadowSettings(enabled=True),
    )
    with TestClient(app) as shadow_client:
        created = _create(shadow_client, transcript)
        mission_id = created["mission"]["id"]
        before = shadow_client.get(f"/v1/missions/{mission_id}").json()
        with app.state.database.reader() as connection:
            before_counts = {
                table: connection.execute(
                    f"SELECT COUNT(*) AS count FROM {table} WHERE mission_id = ?",
                    (mission_id,),
                ).fetchone()["count"]
                for table in ("baskets", "approval_requests", "orders", "payment_attempts")
            }
            before_shadow_decisions = connection.execute(
                "SELECT COUNT(*) AS count FROM portfolio_decisions WHERE mission_id = ? AND execution_mode = 'shadow'",
                (mission_id,),
            ).fetchone()["count"]

        response = shadow_client.post(f"/v1/missions/{mission_id}/portfolio-shadow")
        assert response.status_code == 200, response.text
        run_audit = response.json()
        after = shadow_client.get(f"/v1/missions/{mission_id}").json()
        assert after["mission"]["status"] == before["mission"]["status"]
        assert after["mission"]["revision"] == before["mission"]["revision"]
        assert after["portfolio_decision"]["execution_mode"] == "active"
        assert after["portfolio_decision"]["id"] == before["portfolio_decision"]["id"]
        assert run_audit["not_executed_reason"] == "shadow_mode_enabled; execution_disabled"

        audits = shadow_client.get(
            f"/v1/missions/{mission_id}/portfolio-shadow-audits"
        ).json()
        assert audits["total"] == 2  # automatic run plus the explicit operator run
        latest_audit = audits["items"][-1]
        assert latest_audit["not_executed_reason"] == "shadow_mode_enabled; execution_disabled"
        assert latest_audit["snapshot_id"]
        assert latest_audit["solver_time_ms"] >= 0
        assert "price_delta_cents" in latest_audit["difference"]

        with app.state.database.reader() as connection:
            after_counts = {
                table: connection.execute(
                    f"SELECT COUNT(*) AS count FROM {table} WHERE mission_id = ?",
                    (mission_id,),
                ).fetchone()["count"]
                for table in ("baskets", "approval_requests", "orders", "payment_attempts")
            }
            after_shadow_decisions = connection.execute(
                "SELECT COUNT(*) AS count FROM portfolio_decisions WHERE mission_id = ? AND execution_mode = 'shadow'",
                (mission_id,),
            ).fetchone()["count"]

        assert after_counts == before_counts
        assert after_shadow_decisions == before_shadow_decisions + 1

        telemetry = shadow_client.get("/v1/portfolio/shadow/telemetry").json()
        assert telemetry["enabled"] is True
        assert telemetry["autonomy_enabled"] is False
        assert telemetry["metrics"]["total_shadow_runs"] == 2
        assert "feasibility_rate" in telemetry["metrics"]
        assert "orange_mode_rate" in telemetry["metrics"]
        assert "solver_time_ms_avg" in telemetry["metrics"]
        assert "replan_rate" in telemetry["metrics"]
        assert "recommendation_difference_rate" in telemetry["metrics"]
        assert "price_delta_rate_avg" in telemetry["metrics"]


def test_shadow_mode_and_autonomy_are_disabled_by_default(
    client: TestClient, transcript: str
) -> None:
    created = _create(client, transcript)
    mission_id = created["mission"]["id"]

    response = client.post(f"/v1/missions/{mission_id}/portfolio-shadow")
    assert response.status_code == 409
    capabilities = client.get("/v1/runtime/capabilities").json()["portfolio_automation"]
    assert capabilities["shadow_mode"] is False
    assert capabilities["autonomy_enabled"] is False
    assert capabilities["automatic_purchases_default"] is False
    assert capabilities["promotion_gate"]["requires_manual_approval"] is True


def test_gift_checkout_never_references_a_party_portfolio_decision(
    client: TestClient,
) -> None:
    created = _create(
        client,
        "Buy gifts for five kids aged ten, in a week at 4:30 pm, budget 500 PLN",
    )

    assert created["mission"]["status"] == "approval_required"
    assert created["contract"]["needs"] == []
    assert created["portfolio_decision"] is None
    assert created["approval"]["decision_id"] is None
    assert sum(item["quantity"] for item in created["basket"]["items"]) == 5
    assert {
        item["category"] for item in created["basket"]["items"]
    }.issubset({"toys", "books", "games", "creative"})

    replan = client.post(
        f"/v1/missions/{created['mission']['id']}/replan",
        json={"expected_revision": created["mission"]["revision"]},
    )
    assert replan.status_code == 409
    assert "not available for gift missions" in replan.json()["message"]

    unchanged = client.get(f"/v1/missions/{created['mission']['id']}").json()
    assert unchanged["approval"]["id"] == created["approval"]["id"]
    assert unchanged["basket"]["id"] == created["basket"]["id"]


def test_explicit_recipient_age_keeps_catalog_and_portfolio_candles_aligned(
    client: TestClient,
) -> None:
    created = _create(
        client,
        "Za tydzień przyjęcie dla 5 20-latków. Kup dekoracje, tort, napoje "
        "i przekąski do 1000 PLN, dostawa do 18:00.",
    )

    assert created["mission"]["status"] == "approval_required"
    candle_need = next(
        need for need in created["contract"]["needs"] if need["id"] == "candles"
    )
    candle_item = next(
        item for item in created["basket"]["items"] if item["category"] == "candles"
    )
    candle_action = next(
        action
        for action in created["portfolio_decision"]["actions"]
        if action["need_id"] == "candles"
    )
    assert candle_need["quantity"] == 2
    assert candle_item["quantity"] == 2
    assert candle_action["quantity"] == 2


def test_disagreeing_planners_stop_before_approval_and_funding(
    client: TestClient,
    transcript: str,
    monkeypatch,
) -> None:
    original_plan = CatalogPlanningAgent.plan

    def divergent_plan(agent, request, offers):
        plan = original_plan(agent, request, offers)
        lines = tuple(
            PlannedCatalogLine("snack-crackers", line.quantity)
            if line.product_id == "snack-pretzels"
            else line
            for line in plan.lines
        )
        return replace(plan, lines=lines)

    monkeypatch.setattr(CatalogPlanningAgent, "plan", divergent_plan)

    created = _create(client, transcript)

    assert created["mission"]["status"] == "waiting_for_support"
    assert created["basket"] is None
    assert created["approval"] is None
    assert created["funding"]["status"] == "not_ready"
    action = next(
        item
        for item in created["action_requests"]
        if item["reason_code"] == "PLANNERS_DISAGREE"
    )
    assert action["owner"] == "support"
