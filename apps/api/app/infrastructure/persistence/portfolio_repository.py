"""SQLite persistence for immutable market snapshots and portfolio decisions."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import json
import sqlite3
from typing import Any
from uuid import uuid4

from app.domain.portfolio.enums import (
    ActionKind,
    PortfolioDecisionStatus,
    PortfolioTrigger,
    PriceSignalKind,
    TimingMode,
)
from app.domain.portfolio.model import (
    CandidateAction,
    CandidateOffer,
    FailureRiskSignal,
    LPTBSignal,
    MarketSnapshot,
    PlanState,
    PortfolioDecision,
    PriceSignal,
)
from app.domain.portfolio.needs import needs_from_payload, needs_to_payload, party_needs


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _load(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _timestamp(value: datetime) -> str:
    """Persist and compare timestamps in one canonical timezone."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="milliseconds")


class PortfolioRepository:
    """Stores every planner input and output needed for a later reconstruction."""

    def get_or_create_plan_state(
        self, connection: sqlite3.Connection, mission_id: str
    ) -> PlanState:
        mission = connection.execute(
            "SELECT id, budget_limit_cents, currency, deadline FROM missions WHERE id = ?",
            (mission_id,),
        ).fetchone()
        contract = connection.execute(
            """
            SELECT * FROM mission_contracts
            WHERE mission_id = ? ORDER BY version DESC LIMIT 1
            """,
            (mission_id,),
        ).fetchone()
        if mission is None or contract is None:
            raise LookupError(f"Mission {mission_id} has no current contract")
        existing = connection.execute(
            """
            SELECT * FROM plan_states
            WHERE mission_id = ? AND contract_version = ?
            """,
            (mission_id, contract["version"]),
        ).fetchone()
        if existing is not None:
            return self._plan_state(existing)

        state_id = _id("pst")
        needs = needs_from_payload(_load(contract["needs_json"], []))
        if not needs:
            participants = _load(contract["participants_json"], [])
            participant_count = sum(
                int(item.get("count", 0))
                for item in participants
                if isinstance(item, dict)
            )
            needs = party_needs(participant_count)
        created_at = datetime.now(UTC).isoformat(timespec="milliseconds")
        connection.execute(
            """
            INSERT INTO plan_states
                (id, mission_id, contract_version, needs_json, budget_limit_cents,
                 currency, deadline, hard_constraints_json, soft_preferences_json,
                 approval_policy, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                state_id,
                mission_id,
                contract["version"],
                _dump(needs_to_payload(needs)),
                contract["budget_limit_cents"],
                contract["currency"],
                contract["deadline"],
                contract["hard_constraints_json"],
                contract["soft_preferences_json"],
                contract["approval_policy"],
                created_at,
            ),
        )
        row = connection.execute("SELECT * FROM plan_states WHERE id = ?", (state_id,)).fetchone()
        assert row is not None
        return self._plan_state(row)

    def capture_market_snapshot(
        self,
        connection: sqlite3.Connection,
        *,
        mission_id: str,
        now: datetime,
        freshness: timedelta = timedelta(hours=1),
    ) -> MarketSnapshot:
        captured_at = _aware(_timestamp(now))
        product_rows = self._active_product_rows(connection)
        snapshot_id = _id("mkt")
        catalog_hash = self._catalog_hash(product_rows)
        reusable = connection.execute(
            """
            SELECT * FROM market_snapshots
            WHERE mission_id = ? AND catalog_hash = ? AND freshness_deadline > ?
            ORDER BY captured_at DESC, id DESC
            LIMIT 1
            """,
            (mission_id, catalog_hash, _timestamp(captured_at)),
        ).fetchone()
        if reusable is not None:
            return self._market_snapshot_from_row(connection, reusable)

        freshness_deadline = captured_at + freshness
        connection.execute(
            """
            INSERT INTO market_snapshots
                (id, mission_id, captured_at, freshness_deadline, catalog_hash, source, status)
            VALUES (?, ?, ?, ?, ?, 'demo_catalog', 'fresh')
            """,
            (
                snapshot_id,
                mission_id,
                _timestamp(captured_at),
                _timestamp(freshness_deadline),
                catalog_hash,
            ),
        )
        offers: list[CandidateOffer] = []
        for row in product_rows:
            offer_id = _id("ofs")
            p95_days = self._p95_delivery_days(row)
            tags = self._offer_tags(row)
            available = row["stock"] > 0
            connection.execute(
                """
                INSERT INTO offer_snapshots
                    (id, snapshot_id, product_id, merchant_id, category, price_cents,
                     currency, stock, rating, merchant_reliability, delivery_success_rate,
                     p95_delivery_days, tags_json, nut_free, available)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    offer_id,
                    snapshot_id,
                    row["id"],
                    row["merchant_id"],
                    row["category"],
                    row["price_cents"],
                    row["currency"],
                    row["stock"],
                    row["rating"],
                    row["reliability_score"],
                    row["delivery_success_rate"],
                    p95_days,
                    _dump(tags),
                    row["nut_free"],
                    int(available),
                ),
            )
            connection.execute(
                """
                INSERT INTO price_observations
                    (id, product_id, offer_snapshot_id, observed_at, price_cents, currency)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    _id("prc"),
                    row["id"],
                    offer_id,
                    _timestamp(captured_at),
                    row["price_cents"],
                    row["currency"],
                ),
            )
            connection.execute(
                """
                INSERT INTO inventory_observations
                    (id, product_id, offer_snapshot_id, observed_at, stock, available)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    _id("inv"),
                    row["id"],
                    offer_id,
                    _timestamp(captured_at),
                    row["stock"],
                    int(available),
                ),
            )
            offers.append(
                CandidateOffer(
                    id=offer_id,
                    snapshot_id=snapshot_id,
                    product_id=row["id"],
                    merchant_id=row["merchant_id"],
                    category=row["category"],
                    price_cents=row["price_cents"],
                    currency=row["currency"],
                    stock=row["stock"],
                    rating=row["rating"],
                    merchant_reliability=row["reliability_score"],
                    delivery_success_rate=row["delivery_success_rate"],
                    p95_delivery_days=p95_days,
                    tags=tags,
                    nut_free=bool(row["nut_free"]),
                    available=available,
                )
            )
        return MarketSnapshot(
            id=snapshot_id,
            mission_id=mission_id,
            captured_at=captured_at,
            freshness_deadline=freshness_deadline,
            catalog_hash=catalog_hash,
            offers=tuple(offers),
        )

    def current_catalog_hash(self, connection: sqlite3.Connection) -> str:
        """Return a hash of every catalog attribute used by the planner."""

        return self._catalog_hash(self._active_product_rows(connection))

    def reusable_decision_id(
        self,
        connection: sqlite3.Connection,
        *,
        mission_id: str,
        trigger: PortfolioTrigger,
        now: datetime,
    ) -> str | None:
        """Find a current decision suitable for an idempotent trigger retry.

        A previous decision is reusable only when it is the latest decision for
        the mission, targets the current contract and catalog, and its input
        snapshot has not expired. A later decision from another trigger must
        never be hidden by an older matching trigger.
        """

        catalog_hash = self.current_catalog_hash(connection)
        row = connection.execute(
            """
            SELECT decision.id
            FROM portfolio_decisions AS decision
            JOIN plan_states AS state ON state.id = decision.plan_state_id
            JOIN market_snapshots AS snapshot ON snapshot.id = decision.snapshot_id
            WHERE decision.mission_id = ?
              AND decision.trigger = ?
              AND state.contract_version = (
                    SELECT MAX(version) FROM mission_contracts WHERE mission_id = ?
              )
              AND snapshot.catalog_hash = ?
              AND snapshot.freshness_deadline > ?
              AND decision.execution_mode = 'active'
              AND decision.id = (
                    SELECT latest.id
                    FROM portfolio_decisions AS latest
                    WHERE latest.mission_id = ? AND latest.execution_mode = 'active'
                    ORDER BY latest.rowid DESC
                    LIMIT 1
              )
            """,
            (
                mission_id,
                trigger.value,
                mission_id,
                catalog_hash,
                _timestamp(now),
                mission_id,
            ),
        ).fetchone()
        return str(row["id"]) if row is not None else None

    def decision_for_idempotency_key(
        self, connection: sqlite3.Connection, idempotency_key: str
    ) -> PortfolioDecision | None:
        """Rehydrate a persisted decision instead of producing a duplicate run."""

        row = connection.execute(
            """
            SELECT * FROM portfolio_decisions
            WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()
        return self._decision_from_row(connection, row) if row is not None else None

    @staticmethod
    def _active_product_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
        return connection.execute(
            """
            SELECT p.*, m.reliability_score, m.delivery_success_rate
            FROM products AS p
            JOIN merchants AS m ON m.id = p.merchant_id
            WHERE m.active = 1
            ORDER BY p.id ASC
            """
        ).fetchall()

    @staticmethod
    def _catalog_hash(rows: list[sqlite3.Row]) -> str:
        catalog_payload = [
            {
                "id": row["id"],
                "merchant": row["merchant_id"],
                "category": row["category"],
                "price": row["price_cents"],
                "currency": row["currency"],
                "stock": row["stock"],
                "rating": row["rating"],
                "delivery": row["delivery_class"],
                "merchant_reliability": row["reliability_score"],
                "delivery_success_rate": row["delivery_success_rate"],
                "tags": _load(row["tags_json"], []),
                "substitute_group": row["substitute_group"],
                "nut_free": row["nut_free"],
            }
            for row in rows
        ]
        return sha256(_dump(catalog_payload).encode()).hexdigest()

    @staticmethod
    def _p95_delivery_days(row: sqlite3.Row) -> int:
        return 1 + int(float(row["delivery_success_rate"]) < 0.9)

    @staticmethod
    def _offer_tags(row: sqlite3.Row) -> tuple[str, ...]:
        raw_tags = _load(row["tags_json"], [])
        tags = [str(tag) for tag in raw_tags] if isinstance(raw_tags, list) else []
        if row["substitute_group"]:
            tags.append(str(row["substitute_group"]))
        return tuple(tags)

    def _market_snapshot_from_row(
        self, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> MarketSnapshot:
        offer_rows = connection.execute(
            """
            SELECT * FROM offer_snapshots
            WHERE snapshot_id = ?
            ORDER BY product_id ASC, id ASC
            """,
            (row["id"],),
        ).fetchall()
        return MarketSnapshot(
            id=row["id"],
            mission_id=row["mission_id"],
            captured_at=_aware(row["captured_at"]),
            freshness_deadline=_aware(row["freshness_deadline"]),
            catalog_hash=row["catalog_hash"],
            offers=tuple(self._offer_from_snapshot(offer) for offer in offer_rows),
        )

    @staticmethod
    def _offer_from_snapshot(row: sqlite3.Row) -> CandidateOffer:
        raw_tags = _load(row["tags_json"], [])
        return CandidateOffer(
            id=row["id"],
            snapshot_id=row["snapshot_id"],
            product_id=row["product_id"],
            merchant_id=row["merchant_id"],
            category=row["category"],
            price_cents=int(row["price_cents"]),
            currency=row["currency"],
            stock=int(row["stock"]),
            rating=float(row["rating"]),
            merchant_reliability=float(row["merchant_reliability"]),
            delivery_success_rate=float(row["delivery_success_rate"]),
            p95_delivery_days=int(row["p95_delivery_days"]),
            tags=(tuple(str(tag) for tag in raw_tags) if isinstance(raw_tags, list) else ()),
            nut_free=bool(row["nut_free"]),
            available=bool(row["available"]),
        )

    def price_history(
        self, connection: sqlite3.Connection, product_id: str
    ) -> tuple[int, ...]:
        rows = connection.execute(
            """
            SELECT price_cents FROM price_observations
            WHERE product_id = ? ORDER BY observed_at ASC LIMIT 20
            """,
            (product_id,),
        ).fetchall()
        return tuple(int(row["price_cents"]) for row in rows)

    def persist_decision(
        self,
        connection: sqlite3.Connection,
        decision: PortfolioDecision,
        *,
        considered_actions: tuple[CandidateAction, ...],
        wall_time_ms: int,
        diagnostics: tuple[str, ...],
    ) -> None:
        connection.execute(
            """
            INSERT INTO portfolio_decisions
                (id, mission_id, plan_state_id, snapshot_id, trigger, idempotency_key,
                 status, selected_merchant_id, total_cents, currency, execution_mode,
                 constraint_report_json, explanations_json, solver_metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision.id,
                decision.mission_id,
                decision.plan_state_id,
                decision.snapshot_id,
                decision.trigger.value,
                decision.idempotency_key,
                decision.status.value,
                decision.selected_merchant_id,
                decision.total_cents,
                decision.currency,
                decision.execution_mode,
                _dump(list(decision.constraint_report)),
                _dump(list(decision.explanations)),
                _dump(decision.solver_metadata),
                (decision.created_at or datetime.now(UTC)).isoformat(timespec="milliseconds"),
            ),
        )
        selected_ids = {action.id for action in decision.selected_actions}
        for action in considered_actions:
            connection.execute(
                """
                INSERT INTO portfolio_actions
                    (id, decision_id, need_id, quantity, offer_snapshot_id, product_id, merchant_id,
                     action, selected, timing_mode, price_signal, risk_score, lptb,
                     objective_cost_cents, explanation_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _id("act"),
                    decision.id,
                    action.need_id,
                    action.quantity,
                    action.offer.id,
                    action.offer.product_id,
                    action.offer.merchant_id,
                    action.action.value,
                    int(action.id in selected_ids),
                    action.timing_mode.value,
                    action.price_signal.kind.value,
                    action.failure_risk.probability,
                    action.lptb.lptb.isoformat() if action.lptb else None,
                    action.objective_cost_cents,
                    _dump(
                        {
                            "message": action.explanation,
                            "price_reason": action.price_signal.reason,
                            "risk_reason": action.failure_risk.reason,
                            "lptb_reason": action.lptb.reason if action.lptb else None,
                        }
                    ),
                ),
            )
        connection.execute(
            """
            INSERT INTO optimizer_runs
                (id, decision_id, solver_name, status, wall_time_ms, config_json, diagnostics_json)
            VALUES (?, ?, 'ortools_cp_sat', ?, ?, ?, ?)
            """,
            (
                _id("run"),
                decision.id,
                decision.status.value,
                wall_time_ms,
                _dump(decision.solver_metadata),
                _dump(list(diagnostics)),
            ),
        )

    def latest_decision_projection(
        self, connection: sqlite3.Connection, mission_id: str
    ) -> dict[str, object] | None:
        row = connection.execute(
            """
            SELECT * FROM portfolio_decisions
            WHERE mission_id = ? AND execution_mode = 'active'
            ORDER BY created_at DESC, rowid DESC LIMIT 1
            """,
            (mission_id,),
        ).fetchone()
        return self._decision_projection(connection, row) if row else None

    def latest_active_decision(
        self, connection: sqlite3.Connection, mission_id: str
    ) -> PortfolioDecision | None:
        row = connection.execute(
            """
            SELECT * FROM portfolio_decisions
            WHERE mission_id = ? AND execution_mode = 'active'
            ORDER BY created_at DESC, rowid DESC LIMIT 1
            """,
            (mission_id,),
        ).fetchone()
        return self._decision_from_row(connection, row) if row else None

    def decision_history_projection(
        self, connection: sqlite3.Connection, mission_id: str
    ) -> list[dict[str, object]]:
        rows = connection.execute(
            """
            SELECT * FROM portfolio_decisions
            WHERE mission_id = ? AND execution_mode = 'active'
            ORDER BY created_at ASC, rowid ASC
            """,
            (mission_id,),
        ).fetchall()
        return [self._decision_projection(connection, row) for row in rows]

    def persist_shadow_audit(
        self,
        connection: sqlite3.Connection,
        *,
        mission_id: str,
        trigger: PortfolioTrigger,
        shadow_decision: PortfolioDecision,
        active_decision: PortfolioDecision | None,
        active_basket: sqlite3.Row | None,
        shadow_recommendation: list[dict[str, object]],
        active_recommendation: list[dict[str, object]],
        difference: dict[str, object],
        not_executed_reason: str,
        solver_time_ms: int,
        price_delta_cents: int | None,
    ) -> dict[str, object]:
        audit_id = _id("sha")
        active_basket_total = int(active_basket["total_cents"]) if active_basket else None
        active_decision_total = active_decision.total_cents if active_decision else None
        recommendation_changed = bool(difference.get("recommendation_changed", False))
        connection.execute(
            """
            INSERT INTO portfolio_shadow_audits
                (id, mission_id, shadow_decision_id, active_decision_id, active_basket_id,
                 trigger, snapshot_id, shadow_status, shadow_total_cents,
                 active_decision_total_cents, active_basket_total_cents,
                 shadow_recommendation_json, active_recommendation_json, difference_json,
                 not_executed_reason, feasible, orange_mode, solver_time_ms,
                 price_delta_cents, recommendation_changed, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                mission_id,
                shadow_decision.id,
                active_decision.id if active_decision else None,
                active_basket["id"] if active_basket else None,
                trigger.value,
                shadow_decision.snapshot_id,
                shadow_decision.status.value,
                shadow_decision.total_cents,
                active_decision_total,
                active_basket_total,
                _dump(shadow_recommendation),
                _dump(active_recommendation),
                _dump(difference),
                not_executed_reason,
                int(shadow_decision.status in {PortfolioDecisionStatus.FEASIBLE, PortfolioDecisionStatus.WAITING}),
                int(any(action.timing_mode.value == "orange" for action in shadow_decision.selected_actions)),
                solver_time_ms,
                price_delta_cents,
                int(recommendation_changed),
                shadow_decision.created_at.isoformat(timespec="milliseconds") if shadow_decision.created_at else _timestamp(datetime.now(UTC)),
            ),
        )
        row = connection.execute(
            "SELECT * FROM portfolio_shadow_audits WHERE id = ?", (audit_id,)
        ).fetchone()
        assert row is not None
        return self._shadow_audit_projection(row)

    def shadow_audit_history_projection(
        self, connection: sqlite3.Connection, mission_id: str
    ) -> list[dict[str, object]]:
        rows = connection.execute(
            """
            SELECT * FROM portfolio_shadow_audits
            WHERE mission_id = ? ORDER BY created_at ASC, rowid ASC
            """,
            (mission_id,),
        ).fetchall()
        return [self._shadow_audit_projection(row) for row in rows]

    def shadow_telemetry_projection(
        self, connection: sqlite3.Connection, mission_id: str | None = None
    ) -> dict[str, object]:
        where = "WHERE mission_id = ?" if mission_id else ""
        params = (mission_id,) if mission_id else ()
        rows = connection.execute(
            f"SELECT * FROM portfolio_shadow_audits {where} ORDER BY created_at ASC, rowid ASC",
            params,
        ).fetchall()
        total = len(rows)
        feasible = sum(bool(row["feasible"]) for row in rows)
        orange = sum(bool(row["orange_mode"]) for row in rows)
        replans = sum(row["trigger"] in {"contract_revised", "manual_replan"} for row in rows)
        recommendation_changes = sum(bool(row["recommendation_changed"]) for row in rows)
        deltas = [int(row["price_delta_cents"]) for row in rows if row["price_delta_cents"] is not None]
        relative_deltas = [
            abs(int(row["price_delta_cents"])) / max(
                int(row["active_basket_total_cents"] or row["active_decision_total_cents"] or 0), 1
            )
            for row in rows
            if row["price_delta_cents"] is not None
        ]
        return {
            "total_shadow_runs": total,
            "feasible_runs": feasible,
            "feasibility_rate": feasible / total if total else 0.0,
            "orange_mode_runs": orange,
            "orange_mode_rate": orange / total if total else 0.0,
            "solver_time_ms_avg": sum(int(row["solver_time_ms"]) for row in rows) / total if total else 0.0,
            "replan_runs": replans,
            "replan_rate": replans / total if total else 0.0,
            "recommendation_difference_runs": recommendation_changes,
            "recommendation_difference_rate": recommendation_changes / total if total else 0.0,
            "price_delta_avg_cents": sum(deltas) / len(deltas) if deltas else 0.0,
            "price_delta_abs_avg_cents": sum(abs(delta) for delta in deltas) / len(deltas) if deltas else 0.0,
            "price_delta_rate_avg": sum(relative_deltas) / len(relative_deltas) if relative_deltas else 0.0,
        }

    @staticmethod
    def _plan_state(row: sqlite3.Row) -> PlanState:
        needs = needs_from_payload(_load(row["needs_json"], []))
        hard = tuple(_load(row["hard_constraints_json"], []))
        soft = tuple(_load(row["soft_preferences_json"], []))
        return PlanState(
            id=row["id"],
            mission_id=row["mission_id"],
            contract_version=int(row["contract_version"]),
            needs=needs,
            budget_cents=int(row["budget_limit_cents"]),
            currency=row["currency"],
            deadline=_aware(row["deadline"]),
            approval_policy=row["approval_policy"],
            hard_constraints=hard,
            soft_preferences=soft,
        )

    def _decision_from_row(
        self, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> PortfolioDecision:
        action_rows = connection.execute(
            """
            SELECT
                action.need_id,
                action.quantity,
                action.action,
                action.timing_mode,
                action.price_signal,
                action.risk_score,
                action.lptb,
                action.objective_cost_cents,
                action.explanation_json,
                offer.id AS offer_id,
                offer.snapshot_id AS offer_snapshot_id,
                offer.product_id AS offer_product_id,
                offer.merchant_id AS offer_merchant_id,
                offer.category AS offer_category,
                offer.price_cents AS offer_price_cents,
                offer.currency AS offer_currency,
                offer.stock AS offer_stock,
                offer.rating AS offer_rating,
                offer.merchant_reliability AS offer_merchant_reliability,
                offer.delivery_success_rate AS offer_delivery_success_rate,
                offer.p95_delivery_days AS offer_p95_delivery_days,
                offer.tags_json AS offer_tags_json,
                offer.nut_free AS offer_nut_free,
                offer.available AS offer_available
            FROM portfolio_actions AS action
            JOIN offer_snapshots AS offer ON offer.id = action.offer_snapshot_id
            WHERE action.decision_id = ? AND action.selected = 1
            ORDER BY action.rowid ASC
            """,
            (row["id"],),
        ).fetchall()
        metadata = _load(row["solver_metadata_json"], {})
        return PortfolioDecision(
            id=row["id"],
            mission_id=row["mission_id"],
            plan_state_id=row["plan_state_id"],
            snapshot_id=row["snapshot_id"],
            trigger=PortfolioTrigger(row["trigger"]),
            idempotency_key=row["idempotency_key"],
            status=PortfolioDecisionStatus(row["status"]),
            selected_actions=tuple(self._replay_action(action) for action in action_rows),
            selected_merchant_id=row["selected_merchant_id"],
            total_cents=int(row["total_cents"]),
            currency=row["currency"],
            constraint_report=tuple(
                str(item) for item in _load(row["constraint_report_json"], [])
            ),
            explanations=tuple(str(item) for item in _load(row["explanations_json"], [])),
            solver_metadata=metadata if isinstance(metadata, dict) else {},
            execution_mode=row["execution_mode"],
            created_at=_aware(row["created_at"]),
        )

    @staticmethod
    def _replay_action(row: sqlite3.Row) -> CandidateAction:
        explanation = _load(row["explanation_json"], {})
        details = explanation if isinstance(explanation, dict) else {}
        raw_tags = _load(row["offer_tags_json"], [])
        offer = CandidateOffer(
            id=row["offer_id"],
            snapshot_id=row["offer_snapshot_id"],
            product_id=row["offer_product_id"],
            merchant_id=row["offer_merchant_id"],
            category=row["offer_category"],
            price_cents=int(row["offer_price_cents"]),
            currency=row["offer_currency"],
            stock=int(row["offer_stock"]),
            rating=float(row["offer_rating"]),
            merchant_reliability=float(row["offer_merchant_reliability"]),
            delivery_success_rate=float(row["offer_delivery_success_rate"]),
            p95_delivery_days=int(row["offer_p95_delivery_days"]),
            tags=(tuple(str(tag) for tag in raw_tags) if isinstance(raw_tags, list) else ()),
            nut_free=bool(row["offer_nut_free"]),
            available=bool(row["offer_available"]),
        )
        lptb = None
        if row["lptb"]:
            lptb = LPTBSignal(
                lptb=date.fromisoformat(row["lptb"]),
                p95_delivery_days=offer.p95_delivery_days,
                safety_buffer_days=1,
                reason=str(details.get("lptb_reason", "Persisted LPTB signal.")),
            )
        objective_cost_cents = int(row["objective_cost_cents"])
        return CandidateAction(
            id=f"{row['offer_id']}:{row['action']}",
            need_id=row["need_id"],
            quantity=int(row["quantity"]),
            offer=offer,
            action=ActionKind(row["action"]),
            timing_mode=TimingMode(row["timing_mode"]),
            price_signal=PriceSignal(
                kind=PriceSignalKind(row["price_signal"]),
                expected_price_cents=objective_cost_cents,
                lower_cents=objective_cost_cents,
                upper_cents=objective_cost_cents,
                confidence=0.0,
                reason=str(details.get("price_reason", "Persisted price signal.")),
            ),
            failure_risk=FailureRiskSignal(
                probability=min(1.0, max(0.0, float(row["risk_score"]))),
                reason=str(details.get("risk_reason", "Persisted risk signal.")),
            ),
            lptb=lptb,
            objective_cost_cents=objective_cost_cents,
            explanation=str(details.get("message", "Replayed persisted action.")),
        )

    @staticmethod
    def _decision_projection(
        connection: sqlite3.Connection, row: sqlite3.Row
    ) -> dict[str, object]:
        actions = connection.execute(
            """
            SELECT pa.*, p.name FROM portfolio_actions pa
            JOIN products p ON p.id = pa.product_id
            WHERE pa.decision_id = ? AND pa.selected = 1
            ORDER BY pa.need_id ASC
            """,
            (row["id"],),
        ).fetchall()
        return {
            "id": row["id"],
            "trigger": row["trigger"],
            "execution_mode": row["execution_mode"],
            "status": row["status"],
            "snapshot_id": row["snapshot_id"],
            "selected_merchant_id": row["selected_merchant_id"],
            "total": row["total_cents"] / 100,
            "currency": row["currency"],
            "constraint_report": _load(row["constraint_report_json"], []),
            "explanations": _load(row["explanations_json"], []),
            "solver_metadata": _load(row["solver_metadata_json"], {}),
            "created_at": row["created_at"],
            "actions": [
                {
                    "need_id": action["need_id"],
                    "quantity": action["quantity"],
                    "product_id": action["product_id"],
                    "product_name": action["name"],
                    "merchant_id": action["merchant_id"],
                    "action": action["action"],
                    "timing_mode": action["timing_mode"],
                    "price_signal": action["price_signal"],
                    "risk_score": action["risk_score"],
                    "lptb": action["lptb"],
                    "objective_cost": action["objective_cost_cents"] / 100,
                    "explanation": _load(action["explanation_json"], {}),
                }
                for action in actions
            ],
        }

    @staticmethod
    def _shadow_audit_projection(row: sqlite3.Row) -> dict[str, object]:
        return {
            "id": row["id"],
            "mission_id": row["mission_id"],
            "shadow_decision_id": row["shadow_decision_id"],
            "active_decision_id": row["active_decision_id"],
            "active_basket_id": row["active_basket_id"],
            "trigger": row["trigger"],
            "snapshot_id": row["snapshot_id"],
            "shadow_status": row["shadow_status"],
            "shadow_total": row["shadow_total_cents"] / 100,
            "active_decision_total": (
                row["active_decision_total_cents"] / 100
                if row["active_decision_total_cents"] is not None
                else None
            ),
            "active_basket_total": (
                row["active_basket_total_cents"] / 100
                if row["active_basket_total_cents"] is not None
                else None
            ),
            "shadow_recommendation": _load(row["shadow_recommendation_json"], []),
            "active_recommendation": _load(row["active_recommendation_json"], []),
            "difference": _load(row["difference_json"], {}),
            "not_executed_reason": row["not_executed_reason"],
            "feasible": bool(row["feasible"]),
            "orange_mode": bool(row["orange_mode"]),
            "solver_time_ms": row["solver_time_ms"],
            "price_delta": (
                row["price_delta_cents"] / 100
                if row["price_delta_cents"] is not None
                else None
            ),
            "recommendation_changed": bool(row["recommendation_changed"]),
            "created_at": row["created_at"],
        }
