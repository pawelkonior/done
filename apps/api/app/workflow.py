"""Deterministic mission workflow and response projections.

The demo deliberately keeps the orchestration deterministic. The same service
boundary can later host a LangGraph runner, while policy checks, persistence,
approvals and commerce side effects remain unchanged.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.application.portfolio_planning_service import PortfolioPlanningService
from app.config import PortfolioShadowSettings
from app.domain.common import Money
from app.domain.mission.model import Constraint, ConstraintKind, MissionContract
from app.domain.mission.policies import (
    BasketLine,
    BasketPolicy,
    BasketSnapshot,
    MissionExecutionPolicy,
)
from app.domain.portfolio.enums import PortfolioDecisionStatus, PortfolioTrigger
from app.domain.portfolio.needs import needs_to_payload, party_needs

from .database import Database


DEFAULT_TRANSCRIPT = (
    "Tomorrow I am organizing a birthday party for ten children. "
    "Buy food, drinks and decorations for under 300 PLN, no nuts, "
    "delivered before 16:00."
)

TOTAL_STEPS = 6
ACTIVE_STATUSES = {
    "created",
    "understanding",
    "planning",
    "searching",
    "optimizing",
    "validating",
    "approval_required",
    "executing",
    "recovering",
    "waiting",
}


class MissionNotFoundError(LookupError):
    pass


class ApprovalNotFoundError(LookupError):
    pass


class WorkflowConflictError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def load_json(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def money(cents: int | None) -> float:
    return float(Decimal(cents or 0) / Decimal(100))


def to_cents(value: str | float | Decimal) -> int:
    normalized = Decimal(str(value).replace(",", "."))
    return int((normalized * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def normalize_failure_type(failure_type: str) -> str:
    return "product_unavailable" if failure_type == "out_of_stock" else failure_type


class MissionWorkflow:
    def __init__(
        self,
        database: Database,
        *,
        portfolio_planner: PortfolioPlanningService | None = None,
        portfolio_shadow_settings: PortfolioShadowSettings | None = None,
    ):
        self.database = database
        self.portfolio_planner = portfolio_planner or PortfolioPlanningService()
        self.portfolio_shadow_settings = portfolio_shadow_settings or PortfolioShadowSettings()

    # ------------------------------------------------------------------
    # Public commands
    # ------------------------------------------------------------------
    def interpret_transcript(
        self, transcript: str, locale: str, timezone: str
    ) -> dict[str, Any]:
        """Build the deterministic, safety-critical part of a mission contract.

        Budget, participants, deadlines, descriptive fields and hard
        constraints all originate here. Keeping this operation public avoids
        adapters reaching into private workflow implementation details.
        """

        return self._interpret(transcript, locale, timezone)

    def create_mission(
        self,
        transcript: str,
        locale: str,
        timezone: str,
        input_mode: str,
        *,
        interpretation: dict[str, Any] | None = None,
        inject_demo_failures: bool = True,
        execution_policy: MissionExecutionPolicy | None = None,
    ) -> dict[str, Any]:
        interpreted = interpretation or self._interpret(transcript, locale, timezone)
        policy = execution_policy or MissionExecutionPolicy()
        mission_id = new_id("mis")
        contract_id = new_id("ctr")
        basket_id = new_id("bsk")
        approval_id = new_id("apr")
        selected_delivery_id = new_id("del")
        now = utc_now()
        contract_needs = needs_to_payload(party_needs(interpreted["participants"]))

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO missions
                    (id, user_id, title, subtitle, raw_voice_transcript, input_mode,
                     status, current_step, total_steps, mission_type,
                     budget_limit_cents, currency, deadline, risk_level,
                     requires_approval, locale, timezone, revision,
                     created_at, updated_at)
                VALUES (?, 'demo-user', ?, ?, ?, ?, 'created', 1, ?,
                        'party_shopping', ?, 'PLN', ?, 42, 1, ?, ?, 1, ?, ?)
                """,
                (
                    mission_id,
                    interpreted["title"],
                    interpreted["subtitle"],
                    transcript,
                    input_mode,
                    TOTAL_STEPS,
                    interpreted["budget_limit_cents"],
                    interpreted["deadline"],
                    locale,
                    timezone,
                    now,
                    now,
                ),
            )
            self._event(
                connection,
                mission_id,
                "mission.created",
                "system",
                "Mission created",
                "Done accepted the mission and started understanding it.",
                payload={"input_mode": input_mode},
            )
            self._set_state(connection, mission_id, "understanding", 2)
            self._event(
                connection,
                mission_id,
                "voice.transcribed",
                "voice",
                "Voice understood",
                transcript,
                payload={"transcript": transcript, "locale": locale},
            )
            self._event(
                connection,
                mission_id,
                "intent.parsed",
                "agent",
                "Intent understood",
                interpreted["confirmation"],
                payload={
                    "goal": "prepare_birthday_party",
                    "confidence": interpreted["confidence"],
                    "missing_information": [],
                },
            )
            connection.execute(
                """
                INSERT INTO mission_contracts
                    (id, mission_id, goal, participants_json, needs_json,
                     hard_constraints_json, soft_preferences_json,
                     budget_limit_cents, currency, deadline, approval_policy,
                     allowed_categories_json, forbidden_categories_json,
                     confidence, version, created_at)
                VALUES (?, ?, 'prepare_birthday_party', ?, ?, ?, ?, ?, 'PLN', ?,
                        ?, ?, ?, ?, 1, ?)
                """,
                (
                    contract_id,
                    mission_id,
                    dump_json([{"type": "children", "count": interpreted["participants"]}]),
                    dump_json(contract_needs),
                    dump_json(interpreted["hard_constraints"]),
                    dump_json(
                        [
                            {"type": "minimize_cost", "priority": "medium"},
                            {"type": "single_delivery", "priority": "high"},
                            {"type": "reliable_merchant", "priority": "high"},
                            {
                                "type": "safe_recovery",
                                "enabled": policy.safe_recovery_enabled,
                            },
                            {
                                "type": "preferred_merchants",
                                "merchant_ids": list(policy.preferred_merchant_ids),
                            },
                            {
                                "type": "user_default_constraints",
                                "values": list(policy.default_constraints),
                            },
                        ]
                    ),
                    interpreted["budget_limit_cents"],
                    interpreted["deadline"],
                    policy.approval_mode,
                    dump_json(
                        [
                            "snacks",
                            "drinks",
                            "cake",
                            "decorations",
                            "tableware",
                            "candles",
                            "napkins",
                            "party bags",
                        ]
                    ),
                    dump_json(["alcohol", "nuts"]),
                    interpreted["confidence"],
                    now,
                ),
            )
            self._event(
                connection,
                mission_id,
                "contract.created",
                "agent",
                "Mission contract ready",
                interpreted["confirmation"],
                payload={"contract_id": contract_id, "version": 1},
            )

            self._set_state(connection, mission_id, "planning", 3)
            self._event(
                connection,
                mission_id,
                "plan.created",
                "agent",
                "Shopping plan created",
                "Done planned snacks, drinks, cake, decorations and tableware.",
                payload={"contract_version": 1},
            )
            self._set_state(connection, mission_id, "searching", 3)
            self._event(
                connection,
                mission_id,
                "catalog.searched",
                "tool",
                "Catalog searched",
                "Found a nut-free set from a reliable merchant.",
                payload={
                    "merchant_id": "merchant-b",
                    "candidates_considered": 14,
                    "preferred_merchant_ids": list(policy.preferred_merchant_ids),
                    "preferred_match": "merchant-b" in policy.preferred_merchant_ids,
                },
            )

            decision = self.portfolio_planner.run(
                connection,
                mission_id=mission_id,
                trigger=PortfolioTrigger.MISSION_CREATED,
                preferred_merchants=policy.preferred_merchant_ids,
            )
            self._event(
                connection,
                mission_id,
                "market.snapshot_captured",
                "tool",
                "Market snapshot captured",
                "The portfolio run uses one immutable catalog and price snapshot.",
                payload={"snapshot_id": decision.snapshot_id, "decision_id": decision.id},
            )
            orange_actions = [
                action
                for action in decision.selected_actions
                if action.timing_mode.value == "orange"
            ]
            if orange_actions:
                self._event(
                    connection,
                    mission_id,
                    "timing.orange_mode",
                    "policy",
                    "Waiting disabled for time-sensitive offers",
                    "One or more offers reached their latest safe point to buy.",
                    severity="warning",
                    payload={"need_ids": [action.need_id for action in orange_actions]},
                )
            if decision.status is PortfolioDecisionStatus.INFEASIBLE_PLAN:
                self._event(
                    connection,
                    mission_id,
                    "portfolio.infeasible",
                    "solver",
                    "No feasible portfolio",
                    "No complete plan satisfies the current hard constraints.",
                    severity="error",
                    payload={"decision_id": decision.id, "reasons": list(decision.constraint_report)},
                )
                self._set_state(connection, mission_id, "failed", 4)
                self._run_shadow_if_enabled(
                    connection,
                    mission_id=mission_id,
                    trigger=PortfolioTrigger.MISSION_CREATED,
                    preferred_merchants=policy.preferred_merchant_ids,
                )
                return self._detail(connection, mission_id)
            if decision.status is PortfolioDecisionStatus.INTERNAL_VALIDATION_ERROR:
                self._event(
                    connection,
                    mission_id,
                    "portfolio.invalid",
                    "policy",
                    "Portfolio validation failed",
                    "The solver result did not pass independent validation.",
                    severity="error",
                    payload={"decision_id": decision.id, "reasons": list(decision.constraint_report)},
                )
                self._set_state(connection, mission_id, "failed", 4)
                self._run_shadow_if_enabled(
                    connection,
                    mission_id=mission_id,
                    trigger=PortfolioTrigger.MISSION_CREATED,
                    preferred_merchants=policy.preferred_merchant_ids,
                )
                return self._detail(connection, mission_id)
            if decision.status is PortfolioDecisionStatus.WAITING:
                self._event(
                    connection,
                    mission_id,
                    "portfolio.waiting",
                    "solver",
                    "Waiting for a safer price point",
                    "The selected offers can safely wait until their latest point to buy.",
                    payload={"decision_id": decision.id, "reasons": list(decision.explanations)},
                )
                self._set_state(connection, mission_id, "waiting", 4)
                self._run_shadow_if_enabled(
                    connection,
                    mission_id=mission_id,
                    trigger=PortfolioTrigger.MISSION_CREATED,
                    preferred_merchants=policy.preferred_merchant_ids,
                )
                return self._detail(connection, mission_id)

            delivery_at = self._delivery_time(interpreted["deadline"], hours_before=2)
            delivery_options = (
                (
                    selected_delivery_id,
                    mission_id,
                    decision.selected_merchant_id,
                    "Priority delivery",
                    delivery_at,
                    1299,
                    0.96,
                    1,
                    1,
                ),
                (
                    new_id("del"),
                    mission_id,
                    decision.selected_merchant_id,
                    "Latest safe slot",
                    self._delivery_time(interpreted["deadline"], hours_before=1),
                    899,
                    0.86,
                    0,
                    1,
                ),
                (
                    new_id("del"),
                    mission_id,
                    decision.selected_merchant_id,
                    "Express backup",
                    self._delivery_time(interpreted["deadline"], hours_before=3),
                    1999,
                    0.99,
                    0,
                    1,
                ),
            )
            connection.executemany(
                """
                INSERT INTO delivery_options
                    (id, mission_id, merchant_id, label, delivery_at, cost_cents,
                     confidence, selected, available)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                delivery_options,
            )

            connection.execute(
                """
                INSERT INTO baskets
                    (id, mission_id, merchant_id, delivery_option_id,
                     subtotal_cents, delivery_cost_cents, total_cents,
                     currency, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 0, 1299, 1299, 'PLN',
                        'proposed', ?, ?)
                """,
                (basket_id, mission_id, decision.selected_merchant_id, selected_delivery_id, now, now),
            )
            for action in decision.selected_actions:
                product_id = action.offer.product_id
                quantity = action.quantity
                product = connection.execute(
                    "SELECT price_cents FROM products WHERE id = ?", (product_id,)
                ).fetchone()
                if product is None:  # Defensive guard for corrupted seed data.
                    raise RuntimeError(f"Missing seeded product: {product_id}")
                connection.execute(
                    """
                    INSERT INTO basket_items
                        (id, basket_id, product_id, quantity, unit_price_cents,
                         substitution_allowed, created_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?)
                    """,
                    (
                        new_id("itm"),
                        basket_id,
                        product_id,
                        quantity,
                        action.offer.price_cents,
                        now,
                    ),
                )
            subtotal, total = self._recalculate_basket(connection, basket_id)
            self._set_state(connection, mission_id, "optimizing", 4)
            self._event(
                connection,
                mission_id,
                "basket.optimized",
                "agent",
                "Basket optimized",
                f"Selected {len(decision.selected_actions)} products for {money(total):.2f} PLN.",
                payload={
                    "basket_id": basket_id,
                    "decision_id": decision.id,
                    "subtotal": money(subtotal),
                    "delivery_cost": 12.99,
                    "total": money(total),
                },
            )

            self._set_state(connection, mission_id, "validating", 4)
            self._validate_basket(
                connection,
                mission_id,
                basket_id,
                interpreted["budget_limit_cents"],
            )
            approval_required = policy.requires_approval(
                Money(total, "PLN"), risk_level=42
            )
            self._event(
                connection,
                mission_id,
                "policy.validated",
                "policy",
                "All constraints satisfied",
                "The basket is nut-free, within budget and deliverable before the deadline.",
                payload={
                    "approved": True,
                    "violations": [],
                    "approval_required": approval_required,
                    "approval_mode": policy.approval_mode,
                    "approval_threshold": money(policy.approval_threshold.minor),
                    "constraint_score": 1.0,
                },
            )

            connection.execute(
                "UPDATE missions SET requires_approval = ? WHERE id = ?",
                (int(approval_required), mission_id),
            )

            if inject_demo_failures:
                # Explicit demo mode only. Production missions never receive synthetic failures.
                self._queue_failure(
                    connection,
                    mission_id,
                    "product_unavailable",
                    {"product_id": "snack-pretzels"},
                )
                self._queue_failure(
                    connection,
                    mission_id,
                    "payment_soft_decline",
                    {"provider": "PSP_A", "decline_code": "DO_NOT_HONOR_SOFT"},
                )

            if approval_required:
                expires_at = (datetime.now(UTC) + timedelta(hours=2)).isoformat(
                    timespec="seconds"
                )
                connection.execute(
                    """
                    INSERT INTO approval_requests
                        (id, mission_id, decision_id, approval_type, question, options_json,
                         status, expires_at, created_at)
                    VALUES (?, ?, ?, 'purchase_approval', ?, ?, 'pending', ?, ?)
                    """,
                    (
                        approval_id,
                        mission_id,
                        decision.id,
                        f"Approve purchase for {money(total):.2f} PLN?",
                        dump_json(
                            [
                                {"id": "approve", "label": "Approve"},
                                {"id": "review", "label": "Review basket"},
                                {"id": "cancel", "label": "Cancel"},
                            ]
                        ),
                        expires_at,
                        now,
                    ),
                )
                self._set_state(connection, mission_id, "approval_required", 5)
                self._event(
                    connection,
                    mission_id,
                    "approval.requested",
                    "agent",
                    "Ready for approval",
                    f"Approve the complete basket for {money(total):.2f} PLN.",
                    severity="action",
                    payload={"approval_id": approval_id, "total": money(total)},
                )
            else:
                self._event(
                    connection,
                    mission_id,
                    "approval.skipped",
                    "policy",
                    "Purchase pre-authorized by policy",
                    "The basket is within the user's autonomous execution boundary.",
                    payload={
                        "approval_mode": policy.approval_mode,
                        "total": money(total),
                        "risk_level": 42,
                    },
                )
                self._execute_approved_mission(connection, mission_id)

            self._run_shadow_if_enabled(
                connection,
                mission_id=mission_id,
                trigger=PortfolioTrigger.MISSION_CREATED,
                preferred_merchants=policy.preferred_merchant_ids,
            )

        return self.get_detail(mission_id)

    def resolve_approval(
        self,
        approval_id: str,
        choice: str,
        voice_transcript: str | None = None,
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            approval = connection.execute(
                "SELECT * FROM approval_requests WHERE id = ?", (approval_id,)
            ).fetchone()
            if approval is None:
                raise ApprovalNotFoundError(approval_id)
            mission_id = approval["mission_id"]
            mission = self._require_mission(connection, mission_id)

            if approval["status"] != "pending":
                # Same-choice retries are safe and return the already materialized result.
                if approval["selected_option"] == choice:
                    return self._detail(connection, mission_id)
                raise WorkflowConflictError("Approval has already been resolved")

            if datetime.fromisoformat(approval["expires_at"]) <= datetime.now(UTC):
                connection.execute(
                    """
                    UPDATE approval_requests
                    SET status = 'expired', resolved_at = ?
                    WHERE id = ?
                    """,
                    (utc_now(), approval_id),
                )
                self._event(
                    connection,
                    mission_id,
                    "approval.expired",
                    "system",
                    "Approval expired",
                    "The purchase plan must be reviewed again before execution.",
                    severity="action",
                    payload={"approval_id": approval_id},
                )
                raise WorkflowConflictError("Approval has expired")

            if choice == "review":
                self._event(
                    connection,
                    mission_id,
                    "approval.review_requested",
                    "user",
                    "Basket review opened",
                    "The basket remains paused until it is approved or cancelled.",
                    severity="action",
                    payload={"approval_id": approval_id},
                )
                return self._detail(connection, mission_id)

            resolved_at = utc_now()
            resulting_status = "approved" if choice == "approve" else "cancelled"
            connection.execute(
                """
                UPDATE approval_requests
                SET status = ?, selected_option = ?, resolved_at = ?
                WHERE id = ?
                """,
                (resulting_status, choice, resolved_at, approval_id),
            )
            self._event(
                connection,
                mission_id,
                "approval.resolved",
                "user",
                "Purchase approved" if choice == "approve" else "Mission cancelled",
                (
                    "The user approved the proposed basket."
                    if choice == "approve"
                    else "The user cancelled the mission before payment."
                ),
                payload={
                    "approval_id": approval_id,
                    "choice": choice,
                    "voice_transcript": voice_transcript,
                },
            )

            if choice == "cancel":
                self._set_state(connection, mission_id, "cancelled", mission["current_step"])
                connection.execute(
                    "UPDATE baskets SET status = 'cancelled', updated_at = ? WHERE mission_id = ?",
                    (utc_now(), mission_id),
                )
                return self._detail(connection, mission_id)

            self._execute_approved_mission(connection, mission_id)
            return self._detail(connection, mission_id)

    def inject_failure(self, mission_id: str, failure_type: str) -> dict[str, Any]:
        failure_type = normalize_failure_type(failure_type)
        with self.database.transaction() as connection:
            mission = self._require_mission(connection, mission_id)
            if mission["status"] in {"completed", "failed", "cancelled"}:
                raise WorkflowConflictError("Cannot inject a failure into a terminal mission")
            existing = connection.execute(
                """
                SELECT * FROM failure_injections
                WHERE mission_id = ? AND failure_type = ? AND status = 'queued'
                ORDER BY created_at DESC LIMIT 1
                """,
                (mission_id, failure_type),
            ).fetchone()
            if existing is not None:
                return self._failure_projection(existing, already_queued=True)

            defaults: dict[str, dict[str, Any]] = {
                "product_unavailable": {"product_id": "snack-pretzels"},
                "price_changed": {"product_id": "snack-pretzels", "increase_percent": 20},
                "delivery_slot_lost": {},
                "payment_soft_decline": {
                    "provider": "PSP_A",
                    "decline_code": "DO_NOT_HONOR_SOFT",
                },
                "payment_hard_decline": {
                    "provider": "PSP_A",
                    "decline_code": "LOST_CARD",
                },
            }
            failure_id = self._queue_failure(
                connection,
                mission_id,
                failure_type,
                defaults[failure_type],
            )
            queued = connection.execute(
                "SELECT * FROM failure_injections WHERE id = ?", (failure_id,)
            ).fetchone()
            assert queued is not None
            return self._failure_projection(queued, already_queued=False)

    def cancel_mission(self, mission_id: str) -> dict[str, Any]:
        with self.database.transaction() as connection:
            mission = self._require_mission(connection, mission_id)
            if mission["status"] == "cancelled":
                return self._detail(connection, mission_id)
            if mission["status"] in {"completed", "failed"}:
                raise WorkflowConflictError("A terminal mission cannot be cancelled")
            self._set_state(connection, mission_id, "cancelled", mission["current_step"])
            connection.execute(
                "UPDATE baskets SET status = 'cancelled', updated_at = ? WHERE mission_id = ?",
                (utc_now(), mission_id),
            )
            connection.execute(
                """
                UPDATE approval_requests
                SET status = 'cancelled', selected_option = 'cancel', resolved_at = ?
                WHERE mission_id = ? AND status = 'pending'
                """,
                (utc_now(), mission_id),
            )
            self._event(
                connection,
                mission_id,
                "mission.cancelled",
                "user",
                "Mission cancelled",
                "The mission was cancelled before purchase execution.",
            )
            return self._detail(connection, mission_id)

    def select_delivery_option(
        self,
        mission_id: str,
        delivery_option_id: str,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """Select and revalidate delivery while the mission is still awaiting approval."""

        with self.database.transaction() as connection:
            mission = self._require_mission(connection, mission_id)
            self._check_revision(mission, expected_revision)
            if mission["status"] not in {
                "optimizing",
                "validating",
                "approval_required",
            }:
                raise WorkflowConflictError(
                    "Delivery can only be changed before purchase execution"
                )
            option = connection.execute(
                """
                SELECT * FROM delivery_options
                WHERE id = ? AND mission_id = ?
                """,
                (delivery_option_id, mission_id),
            ).fetchone()
            if option is None:
                raise WorkflowConflictError("Delivery option does not belong to this mission")
            if not option["available"]:
                raise WorkflowConflictError("Delivery option is no longer available")
            if datetime.fromisoformat(option["delivery_at"]) > datetime.fromisoformat(
                mission["deadline"]
            ):
                raise WorkflowConflictError("Delivery option misses the hard deadline")
            basket = connection.execute(
                "SELECT * FROM baskets WHERE mission_id = ? ORDER BY created_at DESC LIMIT 1",
                (mission_id,),
            ).fetchone()
            if basket is None:
                raise WorkflowConflictError("Mission has no basket")
            if option["merchant_id"] != basket["merchant_id"]:
                raise WorkflowConflictError(
                    "Delivery option is not compatible with the selected checkout merchant"
                )
            if basket["delivery_option_id"] == delivery_option_id:
                return self._detail(connection, mission_id)

            projected_total = basket["subtotal_cents"] + option["cost_cents"]
            if projected_total > mission["budget_limit_cents"]:
                raise WorkflowConflictError("Selected delivery would exceed the hard budget")

            connection.execute(
                "UPDATE delivery_options SET selected = 0 WHERE mission_id = ?",
                (mission_id,),
            )
            connection.execute(
                "UPDATE delivery_options SET selected = 1 WHERE id = ?",
                (delivery_option_id,),
            )
            connection.execute(
                """
                UPDATE baskets
                SET delivery_option_id = ?, delivery_cost_cents = ?, total_cents = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    delivery_option_id,
                    option["cost_cents"],
                    projected_total,
                    utc_now(),
                    basket["id"],
                ),
            )
            self._validate_basket(
                connection, mission_id, basket["id"], mission["budget_limit_cents"]
            )
            self._event(
                connection,
                mission_id,
                "delivery.selected",
                "user",
                "Delivery option changed",
                f"Selected {option['label']} for {money(option['cost_cents']):.2f} PLN.",
                payload={
                    "delivery_option_id": delivery_option_id,
                    "new_total": money(projected_total),
                },
            )
            self._replace_pending_approval(
                connection,
                mission_id,
                projected_total,
                reason="The delivery option changed, so the purchase requires fresh approval.",
            )
            connection.execute(
                """
                UPDATE missions
                SET status = 'approval_required', current_step = 5,
                    revision = revision + 1, updated_at = ?
                WHERE id = ?
                """,
                (utc_now(), mission_id),
            )
            return self._detail(connection, mission_id)

    def apply_correction(
        self,
        mission_id: str,
        correction: str,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """Create an immutable contract revision for the same mission aggregate."""

        correction = correction.strip()
        if len(correction) < 3:
            raise WorkflowConflictError("Correction is too short")
        with self.database.transaction() as connection:
            mission = self._require_mission(connection, mission_id)
            self._check_revision(mission, expected_revision)
            if mission["status"] in {"executing", "recovering", "completed", "failed", "cancelled"}:
                raise WorkflowConflictError("Mission can no longer be corrected")
            contract = connection.execute(
                """
                SELECT * FROM mission_contracts
                WHERE mission_id = ? ORDER BY version DESC LIMIT 1
                """,
                (mission_id,),
            ).fetchone()
            if contract is None:
                raise WorkflowConflictError("Mission has no contract")

            budget_cents = contract["budget_limit_cents"]
            budget_match = re.search(
                r"(?:budget(?:\s+to)?|budżet(?:\s+do|\s+na)?|maximum|max(?:imum)?)"
                r"[^0-9]{0,24}([0-9]+(?:[.,][0-9]{1,2})?)",
                correction,
                re.IGNORECASE,
            )
            if budget_match:
                budget_cents = to_cents(budget_match.group(1))

            deadline = datetime.fromisoformat(contract["deadline"])
            deadline_match = re.search(
                r"(?:before|by|przed|do)\s*([0-2]?[0-9]):([0-5][0-9])",
                correction,
                re.IGNORECASE,
            )
            if deadline_match:
                deadline = deadline.replace(
                    hour=int(deadline_match.group(1)),
                    minute=int(deadline_match.group(2)),
                    second=0,
                    microsecond=0,
                )

            participants = load_json(contract["participants_json"], [])
            needs_json = contract["needs_json"]
            participant_match = re.search(
                r"([0-9]+)\s*(?:children|kids|dzieci)", correction, re.IGNORECASE
            )
            if participant_match:
                participant_count = max(1, int(participant_match.group(1)))
                participants = [
                    {"type": "children", "count": participant_count}
                ]
                needs_json = dump_json(needs_to_payload(party_needs(participant_count)))

            hard_constraints = load_json(contract["hard_constraints_json"], [])
            for constraint in hard_constraints:
                if constraint.get("type") == "budget":
                    constraint["value"] = money(budget_cents)
                elif constraint.get("type") == "delivery_deadline":
                    constraint["value"] = deadline.isoformat()
            normalized = correction.casefold()
            if ("no plastic" in normalized or "bez plastiku" in normalized) and not any(
                item.get("type") == "material" and item.get("value") == "plastic"
                for item in hard_constraints
            ):
                hard_constraints.append(
                    {
                        "type": "material",
                        "operator": "exclude",
                        "value": "plastic",
                    }
                )
            if ("no nuts" in normalized or "bez orzech" in normalized) and not any(
                item.get("type") == "allergen" and item.get("value") == "nuts"
                for item in hard_constraints
            ):
                hard_constraints.append(
                    {"type": "allergen", "operator": "exclude", "value": "nuts"}
                )

            version = contract["version"] + 1
            contract_id = new_id("ctr")
            now = utc_now()
            connection.execute(
                """
                INSERT INTO mission_contracts
                    (id, mission_id, goal, participants_json, needs_json,
                     hard_constraints_json, soft_preferences_json,
                     budget_limit_cents, currency, deadline, approval_policy,
                     allowed_categories_json, forbidden_categories_json,
                     confidence, version, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    contract_id,
                    mission_id,
                    contract["goal"],
                    dump_json(participants),
                    needs_json,
                    dump_json(hard_constraints),
                    contract["soft_preferences_json"],
                    budget_cents,
                    contract["currency"],
                    deadline.isoformat(),
                    contract["approval_policy"],
                    contract["allowed_categories_json"],
                    contract["forbidden_categories_json"],
                    contract["confidence"],
                    version,
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE missions
                SET raw_voice_transcript = raw_voice_transcript || '\nCorrection: ' || ?,
                    budget_limit_cents = ?, deadline = ?, status = 'planning',
                    current_step = 3, revision = revision + 1, updated_at = ?
                WHERE id = ?
                """,
                (correction, budget_cents, deadline.isoformat(), now, mission_id),
            )
            self._event(
                connection,
                mission_id,
                "mission.corrected",
                "user",
                "Mission corrected",
                correction,
                payload={"contract_version": version},
            )
            self._event(
                connection,
                mission_id,
                "contract.revised",
                "agent",
                "Mission contract updated",
                f"Contract version {version} preserves the updated hard constraints.",
                payload={"contract_id": contract_id, "version": version},
            )
            return self._replan_in_transaction(
                connection,
                mission_id=mission_id,
                trigger=PortfolioTrigger.CONTRACT_REVISED,
                increment_revision=False,
            )

    def replan_mission(
        self,
        mission_id: str,
        *,
        expected_revision: int | None = None,
        trigger: PortfolioTrigger = PortfolioTrigger.MANUAL_REPLAN,
    ) -> dict[str, Any]:
        """Rebuild an auditable decision and replace any pending checkout safely."""

        with self.database.transaction() as connection:
            mission = self._require_mission(connection, mission_id)
            self._check_revision(mission, expected_revision)
            if mission["status"] in {"executing", "recovering", "completed", "failed", "cancelled"}:
                raise WorkflowConflictError("Mission can no longer be re-planned")
            if self.portfolio_planner.repository.reusable_decision_id(
                connection,
                mission_id=mission_id,
                trigger=trigger,
                now=datetime.now(UTC),
            ):
                return self._detail(connection, mission_id)
            return self._replan_in_transaction(
                connection,
                mission_id=mission_id,
                trigger=trigger,
                increment_revision=True,
            )

    def get_portfolio_decisions(self, mission_id: str) -> dict[str, Any]:
        with self.database.reader() as connection:
            self._require_mission(connection, mission_id)
            items = self.portfolio_planner.repository.decision_history_projection(
                connection, mission_id
            )
            return {"items": items, "decisions": items, "total": len(items)}

    def run_portfolio_shadow(
        self,
        mission_id: str,
        *,
        trigger: PortfolioTrigger = PortfolioTrigger.MANUAL_REPLAN,
    ) -> dict[str, Any]:
        """Evaluate the planner without touching checkout state."""

        with self.database.transaction() as connection:
            self._require_mission(connection, mission_id)
            return self._run_shadow_in_transaction(
                connection, mission_id=mission_id, trigger=trigger
            )

    def get_portfolio_shadow_audits(self, mission_id: str) -> dict[str, Any]:
        with self.database.reader() as connection:
            self._require_mission(connection, mission_id)
            items = self.portfolio_planner.repository.shadow_audit_history_projection(
                connection, mission_id
            )
            return {"items": items, "audits": items, "total": len(items)}

    def get_portfolio_shadow_telemetry(self, mission_id: str | None = None) -> dict[str, Any]:
        with self.database.reader() as connection:
            if mission_id:
                self._require_mission(connection, mission_id)
            return self.portfolio_planner.repository.shadow_telemetry_projection(
                connection, mission_id
            )

    def _run_shadow_if_enabled(
        self,
        connection: sqlite3.Connection,
        *,
        mission_id: str,
        trigger: PortfolioTrigger,
        preferred_merchants: tuple[str, ...],
    ) -> dict[str, Any] | None:
        if not self.portfolio_shadow_settings.enabled:
            return None
        return self._run_shadow_in_transaction(
            connection,
            mission_id=mission_id,
            trigger=trigger,
            preferred_merchants=preferred_merchants,
        )

    def _run_shadow_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        mission_id: str,
        trigger: PortfolioTrigger,
        preferred_merchants: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        shadow_decision = self.portfolio_planner.run(
            connection,
            mission_id=mission_id,
            trigger=trigger,
            preferred_merchants=preferred_merchants,
            execution_mode="shadow",
        )
        active_decision = self.portfolio_planner.repository.latest_active_decision(
            connection, mission_id
        )
        active_basket = connection.execute(
            """
            SELECT * FROM baskets
            WHERE mission_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1
            """,
            (mission_id,),
        ).fetchone()
        shadow_recommendation = self._decision_recommendation(shadow_decision)
        active_recommendation = (
            self._decision_recommendation(active_decision) if active_decision else []
        )
        basket_recommendation = self._basket_recommendation(connection, active_basket)
        active_total = (
            active_basket["total_cents"]
            if active_basket is not None
            else active_decision.total_cents if active_decision else None
        )
        price_delta = shadow_decision.total_cents - active_total if active_total is not None else None
        recommendation_changed = shadow_recommendation != active_recommendation
        difference = {
            "recommendation_changed": recommendation_changed,
            "basket_recommendation_changed": shadow_recommendation != basket_recommendation,
            "selected_merchant_changed": (
                active_decision is not None
                and shadow_decision.selected_merchant_id != active_decision.selected_merchant_id
            ),
            "status_changed": (
                active_decision is not None
                and shadow_decision.status.value != active_decision.status.value
            ),
            "price_delta_cents": price_delta,
            "active_decision_total_cents": active_decision.total_cents if active_decision else None,
            "active_basket_total_cents": active_basket["total_cents"] if active_basket else None,
        }
        audit = self.portfolio_planner.repository.persist_shadow_audit(
            connection,
            mission_id=mission_id,
            trigger=trigger,
            shadow_decision=shadow_decision,
            active_decision=active_decision,
            active_basket=active_basket,
            shadow_recommendation=shadow_recommendation,
            active_recommendation=active_recommendation,
            difference=difference,
            not_executed_reason="shadow_mode_enabled; execution_disabled",
            solver_time_ms=int(shadow_decision.solver_metadata.get("solver_time_ms", 0)),
            price_delta_cents=price_delta,
        )
        self._event(
            connection,
            mission_id,
            "portfolio.shadow_audit",
            "shadow_solver",
            "Shadow portfolio decision recorded",
            "The shadow recommendation was evaluated on live catalog data and not executed.",
            severity="warning" if recommendation_changed else "info",
            payload={
                "audit_id": audit["id"],
                "trigger": trigger.value,
                "shadow_decision_id": shadow_decision.id,
                "active_decision_id": active_decision.id if active_decision else None,
                "snapshot_id": shadow_decision.snapshot_id,
                "shadow_recommendation": shadow_recommendation,
                "active_recommendation": active_recommendation,
                "active_basket_recommendation": basket_recommendation,
                "difference": difference,
                "not_executed_reason": "shadow_mode_enabled; execution_disabled",
            },
        )
        return audit

    @staticmethod
    def _decision_recommendation(decision: Any | None) -> list[dict[str, object]]:
        if decision is None:
            return []
        return [
            {
                "product_id": action.offer.product_id,
                "quantity": action.quantity,
                "action": action.action.value,
            }
            for action in decision.selected_actions
        ]

    @staticmethod
    def _basket_recommendation(
        connection: sqlite3.Connection, basket: sqlite3.Row | None
    ) -> list[dict[str, object]]:
        if basket is None:
            return []
        rows = connection.execute(
            """
            SELECT product_id, quantity FROM basket_items
            WHERE basket_id = ? ORDER BY product_id ASC
            """,
            (basket["id"],),
        ).fetchall()
        return [
            {
                "product_id": row["product_id"],
                "quantity": row["quantity"],
                "action": "buy_now",
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Public queries
    # ------------------------------------------------------------------
    def list_missions(
        self,
        status: str | None = None,
        *,
        query_text: str | None = None,
        completed_from: str | None = None,
        completed_to: str | None = None,
        sort: str = "newest",
        requires_action: bool | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM missions"
        parameters: list[Any] = []
        conditions: list[str] = []
        if status:
            normalized = status.lower().strip()
            if normalized == "active":
                placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
                conditions.append(f"status IN ({placeholders})")
                parameters.extend(sorted(ACTIVE_STATUSES))
            else:
                statuses = [part.strip() for part in normalized.split(",") if part.strip()]
                placeholders = ",".join("?" for _ in statuses)
                conditions.append(f"status IN ({placeholders})")
                parameters.extend(statuses)
        if query_text:
            conditions.append("(LOWER(title) LIKE ? OR LOWER(subtitle) LIKE ?)")
            pattern = f"%{query_text.casefold().strip()}%"
            parameters.extend([pattern, pattern])
        if completed_from:
            conditions.append("completed_at >= ?")
            parameters.append(completed_from)
        if completed_to:
            conditions.append("completed_at <= ?")
            parameters.append(completed_to)
        if requires_action is True:
            conditions.append("status = 'approval_required'")
        elif requires_action is False:
            conditions.append("status != 'approval_required'")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        order_by = {
            "newest": "created_at DESC",
            "oldest": "created_at ASC",
            "updated": "updated_at DESC",
            "deadline": "deadline ASC",
        }.get(sort, "created_at DESC")
        query += f" ORDER BY {order_by}"
        with self.database.reader() as connection:
            rows = connection.execute(query, parameters).fetchall()
            return [self._mission_summary(connection, row) for row in rows]

    def get_detail(self, mission_id: str) -> dict[str, Any]:
        with self.database.reader() as connection:
            self._require_mission(connection, mission_id)
            return self._detail(connection, mission_id)

    def get_events(self, mission_id: str, after_id: int = 0) -> dict[str, Any]:
        with self.database.reader() as connection:
            self._require_mission(connection, mission_id)
            rows = connection.execute(
                """
                SELECT * FROM mission_events
                WHERE mission_id = ? AND id > ?
                ORDER BY id ASC
                """,
                (mission_id, after_id),
            ).fetchall()
            items = [self._event_projection(row) for row in rows]
            cursor = items[-1]["id"] if items else after_id
            mission = connection.execute(
                "SELECT revision, status, updated_at FROM missions WHERE id = ?",
                (mission_id,),
            ).fetchone()
            assert mission is not None
            return {
                "events": items,
                "items": items,
                "cursor": cursor,
                "mission_status": mission["status"],
                "revision": mission["revision"],
                "updated_at": mission["updated_at"],
            }

    # ------------------------------------------------------------------
    # Workflow internals
    # ------------------------------------------------------------------
    def _replan_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        mission_id: str,
        trigger: PortfolioTrigger,
        increment_revision: bool,
    ) -> dict[str, Any]:
        contract = connection.execute(
            """
            SELECT * FROM mission_contracts
            WHERE mission_id = ? ORDER BY version DESC LIMIT 1
            """,
            (mission_id,),
        ).fetchone()
        if contract is None:
            raise WorkflowConflictError("Mission has no contract")
        policy = self._execution_policy_from_contract(contract)
        decision = self.portfolio_planner.run(
            connection,
            mission_id=mission_id,
            trigger=trigger,
            preferred_merchants=policy.preferred_merchant_ids,
        )
        self._event(
            connection,
            mission_id,
            "market.snapshot_captured",
            "tool",
            "Market snapshot captured",
            "The replan uses one immutable catalog and price snapshot.",
            payload={"snapshot_id": decision.snapshot_id, "decision_id": decision.id},
        )
        if decision.status in {
            PortfolioDecisionStatus.INFEASIBLE_PLAN,
            PortfolioDecisionStatus.INTERNAL_VALIDATION_ERROR,
        }:
            self._clear_pending_checkout(connection, mission_id, cancel_approval=True)
            self._event(
                connection,
                mission_id,
                "portfolio.infeasible",
                "solver",
                "No feasible portfolio",
                "No complete plan satisfies the current hard constraints.",
                severity="error",
                payload={"decision_id": decision.id, "reasons": list(decision.constraint_report)},
            )
            self._set_replan_state(
                connection,
                mission_id,
                status="failed",
                current_step=4,
                requires_approval=False,
                increment_revision=increment_revision,
            )
            self._run_shadow_if_enabled(
                connection,
                mission_id=mission_id,
                trigger=trigger,
                preferred_merchants=policy.preferred_merchant_ids,
            )
            return self._detail(connection, mission_id)

        if decision.status is PortfolioDecisionStatus.WAITING:
            self._clear_pending_checkout(connection, mission_id, cancel_approval=True)
            self._event(
                connection,
                mission_id,
                "portfolio.waiting",
                "solver",
                "Waiting for a safer price point",
                "The selected offers can safely wait until their latest point to buy.",
                payload={"decision_id": decision.id, "reasons": list(decision.explanations)},
            )
            self._set_replan_state(
                connection,
                mission_id,
                status="waiting",
                current_step=4,
                requires_approval=False,
                increment_revision=increment_revision,
            )
            self._run_shadow_if_enabled(
                connection,
                mission_id=mission_id,
                trigger=trigger,
                preferred_merchants=policy.preferred_merchant_ids,
            )
            return self._detail(connection, mission_id)

        self._clear_pending_checkout(connection, mission_id, cancel_approval=False)
        basket_id, total = self._materialize_portfolio_basket(
            connection, mission_id=mission_id, contract=contract, decision=decision
        )
        self._validate_basket(
            connection, mission_id, basket_id, contract["budget_limit_cents"]
        )
        approval_required = policy.requires_approval(Money(total, "PLN"), risk_level=42)
        if approval_required:
            approval_id = self._replace_pending_approval(
                connection,
                mission_id,
                total,
                reason="A new portfolio decision replaced the pending checkout.",
                decision_id=decision.id,
            )
        else:
            approval_id = None
        self._event(
            connection,
            mission_id,
            "portfolio.replanned",
            "solver",
            "Portfolio decision refreshed",
            "A validated portfolio was projected into the current basket.",
            payload={
                "decision_id": decision.id,
                "basket_id": basket_id,
                "approval_id": approval_id,
                "total": money(total),
            },
        )
        self._set_replan_state(
            connection,
            mission_id,
            status="approval_required" if approval_required else "executing",
            current_step=5,
            requires_approval=approval_required,
            increment_revision=increment_revision,
        )
        if not approval_required:
            self._execute_approved_mission(connection, mission_id)
        self._run_shadow_if_enabled(
            connection,
            mission_id=mission_id,
            trigger=trigger,
            preferred_merchants=policy.preferred_merchant_ids,
        )
        return self._detail(connection, mission_id)

    def _materialize_portfolio_basket(
        self,
        connection: sqlite3.Connection,
        *,
        mission_id: str,
        contract: sqlite3.Row,
        decision: Any,
    ) -> tuple[str, int]:
        merchant_id = decision.selected_merchant_id
        if merchant_id is None:
            raise WorkflowConflictError("Feasible portfolio has no selected merchant")
        now = utc_now()
        delivery_id = new_id("del")
        delivery_options = (
            (
                delivery_id,
                mission_id,
                merchant_id,
                "Priority delivery",
                self._delivery_time(contract["deadline"], hours_before=2),
                1299,
                0.96,
                1,
                1,
            ),
            (
                new_id("del"),
                mission_id,
                merchant_id,
                "Latest safe slot",
                self._delivery_time(contract["deadline"], hours_before=1),
                899,
                0.86,
                0,
                1,
            ),
            (
                new_id("del"),
                mission_id,
                merchant_id,
                "Express backup",
                self._delivery_time(contract["deadline"], hours_before=3),
                1999,
                0.99,
                0,
                1,
            ),
        )
        connection.executemany(
            """
            INSERT INTO delivery_options
                (id, mission_id, merchant_id, label, delivery_at, cost_cents,
                 confidence, selected, available)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            delivery_options,
        )
        basket_id = new_id("bsk")
        connection.execute(
            """
            INSERT INTO baskets
                (id, mission_id, merchant_id, delivery_option_id, subtotal_cents,
                 delivery_cost_cents, total_cents, currency, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 0, 1299, 1299, 'PLN', 'proposed', ?, ?)
            """,
            (basket_id, mission_id, merchant_id, delivery_id, now, now),
        )
        for action in decision.selected_actions:
            if action.action.value != "buy_now":
                raise WorkflowConflictError("Waiting actions cannot be projected into a checkout")
            connection.execute(
                """
                INSERT INTO basket_items
                    (id, basket_id, product_id, quantity, unit_price_cents,
                     substitution_allowed, created_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    new_id("itm"),
                    basket_id,
                    action.offer.product_id,
                    action.quantity,
                    action.offer.price_cents,
                    now,
                ),
            )
        _, total = self._recalculate_basket(connection, basket_id)
        return basket_id, total

    def _clear_pending_checkout(
        self, connection: sqlite3.Connection, mission_id: str, *, cancel_approval: bool
    ) -> None:
        if cancel_approval:
            pending = connection.execute(
                """
                SELECT id FROM approval_requests
                WHERE mission_id = ? AND status = 'pending'
                ORDER BY created_at DESC LIMIT 1
                """,
                (mission_id,),
            ).fetchone()
            if pending is not None:
                connection.execute(
                    """
                    UPDATE approval_requests
                    SET status = 'cancelled', selected_option = 'superseded', resolved_at = ?
                    WHERE id = ?
                    """,
                    (utc_now(), pending["id"]),
                )
                self._event(
                    connection,
                    mission_id,
                    "approval.superseded",
                    "system",
                    "Previous approval invalidated",
                    "The portfolio decision changed before checkout.",
                    payload={"approval_id": pending["id"]},
                )
        connection.execute("DELETE FROM baskets WHERE mission_id = ?", (mission_id,))
        connection.execute("DELETE FROM delivery_options WHERE mission_id = ?", (mission_id,))

    @staticmethod
    def _execution_policy_from_contract(contract: sqlite3.Row) -> MissionExecutionPolicy:
        preferences = load_json(contract["soft_preferences_json"], [])
        preferred: tuple[str, ...] = ()
        safe_recovery = True
        for preference in preferences:
            if not isinstance(preference, dict):
                continue
            if preference.get("type") == "preferred_merchants":
                preferred = tuple(str(value) for value in preference.get("merchant_ids", []))
            elif preference.get("type") == "safe_recovery":
                safe_recovery = bool(preference.get("enabled", True))
        approval_mode = contract["approval_policy"]
        if approval_mode not in {"always", "autonomous_low_risk"}:
            approval_mode = "always"
        return MissionExecutionPolicy(
            approval_mode=approval_mode,
            safe_recovery_enabled=safe_recovery,
            preferred_merchant_ids=preferred,
        )

    @staticmethod
    def _set_replan_state(
        connection: sqlite3.Connection,
        mission_id: str,
        *,
        status: str,
        current_step: int,
        requires_approval: bool,
        increment_revision: bool,
    ) -> None:
        connection.execute(
            """
            UPDATE missions
            SET status = ?, current_step = ?, requires_approval = ?,
                revision = revision + ?, updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                current_step,
                int(requires_approval),
                int(increment_revision),
                utc_now(),
                mission_id,
            ),
        )

    def _execute_approved_mission(
        self, connection: sqlite3.Connection, mission_id: str
    ) -> None:
        mission = self._require_mission(connection, mission_id)
        basket = connection.execute(
            "SELECT * FROM baskets WHERE mission_id = ?", (mission_id,)
        ).fetchone()
        if basket is None:
            raise WorkflowConflictError("Mission has no basket")

        if not self._safe_recovery_enabled(connection, mission_id):
            blocked_failure = connection.execute(
                """
                SELECT * FROM failure_injections
                WHERE mission_id = ? AND status = 'queued'
                  AND failure_type IN (
                      'product_unavailable', 'price_changed',
                      'delivery_slot_lost', 'payment_soft_decline'
                  )
                ORDER BY created_at ASC LIMIT 1
                """,
                (mission_id,),
            ).fetchone()
            if blocked_failure is not None:
                connection.execute(
                    """
                    UPDATE failure_injections
                    SET status = 'blocked', consumed_at = ?
                    WHERE id = ?
                    """,
                    (utc_now(), blocked_failure["id"]),
                )
                self._set_state(connection, mission_id, "failed", 6)
                connection.execute(
                    """
                    UPDATE baskets SET status = 'intervention_required', updated_at = ?
                    WHERE id = ?
                    """,
                    (utc_now(), basket["id"]),
                )
                self._event(
                    connection,
                    mission_id,
                    "recovery.blocked_by_policy",
                    "policy",
                    "Automatic recovery is disabled",
                    "Execution stopped without changing the basket or retrying payment.",
                    severity="action",
                    payload={
                        "failure_type": blocked_failure["failure_type"],
                        "safe_recovery_enabled": False,
                    },
                )
                self._event(
                    connection,
                    mission_id,
                    "mission.failed",
                    "system",
                    "Mission needs manual intervention",
                    "Enable safe self-healing and create a fresh mission to recover automatically.",
                    severity="error",
                )
                return

        self._set_state(connection, mission_id, "executing", 6)
        self._event(
            connection,
            mission_id,
            "execution.started",
            "agent",
            "Purchase started",
            "Done started inventory reservation and checkout.",
        )

        # Optional injected price change is repaired before reservation.
        price_failure = self._consume_failure(connection, mission_id, "price_changed")
        if price_failure is not None:
            self._set_state(connection, mission_id, "recovering", 6)
            self._event(
                connection,
                mission_id,
                "price.changed",
                "merchant",
                "Price changed",
                "A selected product became more expensive during checkout.",
                severity="warning",
                payload=load_json(price_failure["payload_json"], {}),
            )
            self._event(
                connection,
                mission_id,
                "recovery.started",
                "agent",
                "Re-optimizing basket",
                "Done protected the budget by keeping the validated demo price.",
                payload={"strategy": "preserve_reserved_price"},
            )

        inventory_failure = self._consume_failure(
            connection, mission_id, "product_unavailable"
        )
        if inventory_failure is not None:
            payload = load_json(inventory_failure["payload_json"], {})
            unavailable_id = payload.get("product_id", "snack-pretzels")
            unavailable = connection.execute(
                "SELECT * FROM products WHERE id = ?", (unavailable_id,)
            ).fetchone()
            if unavailable is None:
                raise WorkflowConflictError("Injected unavailable product does not exist")
            self._set_state(connection, mission_id, "recovering", 6)
            self._event(
                connection,
                mission_id,
                "inventory.unavailable",
                "merchant",
                "Product unavailable",
                f"{unavailable['name']} went out of stock during reservation.",
                severity="warning",
                payload={"product_id": unavailable_id, "failure_type": "product_unavailable"},
            )
            self._event(
                connection,
                mission_id,
                "recovery.started",
                "agent",
                "Finding a safe replacement",
                "Done searched for a substitute without relaxing the nut-free constraint.",
                payload={"strategy": "replace_product"},
            )
            replacement = connection.execute(
                """
                SELECT * FROM products
                WHERE id != ? AND merchant_id = ? AND substitute_group = ?
                  AND nut_free = 1 AND stock > 0
                ORDER BY rating DESC, price_cents ASC
                LIMIT 1
                """,
                (
                    unavailable_id,
                    unavailable["merchant_id"],
                    unavailable["substitute_group"],
                ),
            ).fetchone()
            if replacement is None:
                raise WorkflowConflictError("No compliant replacement is available")
            basket_item = connection.execute(
                """
                SELECT * FROM basket_items
                WHERE basket_id = ? AND product_id = ?
                """,
                (basket["id"], unavailable_id),
            ).fetchone()
            if basket_item is None:
                raise WorkflowConflictError("Unavailable product is not in the basket")
            connection.execute(
                """
                UPDATE basket_items
                SET product_id = ?, unit_price_cents = ?, replaced_product_id = ?
                WHERE id = ?
                """,
                (
                    replacement["id"],
                    replacement["price_cents"],
                    unavailable_id,
                    basket_item["id"],
                ),
            )
            _, total = self._recalculate_basket(connection, basket["id"])
            self._validate_basket(
                connection,
                mission_id,
                basket["id"],
                mission["budget_limit_cents"],
            )
            self._event(
                connection,
                mission_id,
                "product.replaced",
                "agent",
                "Product replaced safely",
                f"Replaced {unavailable['name']} with {replacement['name']}.",
                payload={
                    "old_product_id": unavailable_id,
                    "old_product_name": unavailable["name"],
                    "new_product_id": replacement["id"],
                    "new_product_name": replacement["name"],
                    "hard_constraints_preserved": True,
                    "new_total": money(total),
                },
            )
            self._event(
                connection,
                mission_id,
                "policy.validated",
                "policy",
                "Replacement validated",
                "The replacement is nut-free, in budget and delivery-compatible.",
                payload={"approved": True, "violations": [], "constraint_score": 1.0},
            )

        delivery_failure = self._consume_failure(
            connection, mission_id, "delivery_slot_lost"
        )
        if delivery_failure is not None:
            selected = connection.execute(
                """
                SELECT * FROM delivery_options
                WHERE mission_id = ? AND selected = 1
                """,
                (mission_id,),
            ).fetchone()
            backup = connection.execute(
                """
                SELECT * FROM delivery_options
                WHERE mission_id = ? AND selected = 0 AND available = 1
                ORDER BY confidence DESC LIMIT 1
                """,
                (mission_id,),
            ).fetchone()
            if selected is not None and backup is not None:
                self._set_state(connection, mission_id, "recovering", 6)
                connection.execute(
                    "UPDATE delivery_options SET selected = 0, available = 0 WHERE id = ?",
                    (selected["id"],),
                )
                connection.execute(
                    "UPDATE delivery_options SET selected = 1 WHERE id = ?", (backup["id"],)
                )
                connection.execute(
                    """
                    UPDATE baskets
                    SET delivery_option_id = ?, delivery_cost_cents = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (backup["id"], backup["cost_cents"], utc_now(), basket["id"]),
                )
                self._recalculate_basket(connection, basket["id"])
                self._event(
                    connection,
                    mission_id,
                    "delivery.switched",
                    "agent",
                    "Delivery slot recovered",
                    f"Done switched delivery to {backup['label']}.",
                    payload={"old_option_id": selected["id"], "new_option_id": backup["id"]},
                )

        self._set_state(connection, mission_id, "executing", 6)
        self._event(
            connection,
            mission_id,
            "inventory.reserved",
            "merchant",
            "Inventory reserved",
            "All final basket items are reserved.",
            payload={"basket_id": basket["id"]},
        )

        current_basket = connection.execute(
            "SELECT * FROM baskets WHERE id = ?", (basket["id"],)
        ).fetchone()
        assert current_basket is not None
        amount_cents = current_basket["total_cents"]

        hard_failure = self._consume_failure(
            connection, mission_id, "payment_hard_decline"
        )
        soft_failure = None
        if hard_failure is None:
            soft_failure = self._consume_failure(
                connection, mission_id, "payment_soft_decline"
            )

        first_status = "declined" if hard_failure is not None or soft_failure is not None else "authorized"
        first_decline = None
        if hard_failure is not None:
            first_decline = "LOST_CARD"
        elif soft_failure is not None:
            first_decline = "DO_NOT_HONOR_SOFT"
        self._record_payment(
            connection,
            mission_id,
            amount_cents,
            provider="PSP_A",
            status=first_status,
            retry_number=0,
            decline_code=first_decline,
        )
        self._event(
            connection,
            mission_id,
            "payment.attempted",
            "payment",
            "Payment authorization started",
            "PSP_A is authorizing the simulated payment.",
            payload={"provider": "PSP_A", "attempt": 1, "amount": money(amount_cents)},
        )

        if hard_failure is not None:
            self._event(
                connection,
                mission_id,
                "payment.declined",
                "payment",
                "Payment method declined",
                "The payment received a hard decline and was not retried automatically.",
                severity="error",
                payload={"provider": "PSP_A", "decline_code": "LOST_CARD", "retryable": False},
            )
            self._set_state(connection, mission_id, "failed", 6)
            connection.execute(
                "UPDATE baskets SET status = 'payment_failed', updated_at = ? WHERE id = ?",
                (utc_now(), basket["id"]),
            )
            self._event(
                connection,
                mission_id,
                "mission.failed",
                "system",
                "Mission needs a new payment method",
                "No automatic retry was made after the hard decline.",
                severity="error",
            )
            return

        if soft_failure is not None:
            self._event(
                connection,
                mission_id,
                "payment.declined",
                "payment",
                "Payment temporarily declined",
                "PSP_A returned a retryable soft decline.",
                severity="warning",
                payload={
                    "provider": "PSP_A",
                    "decline_code": "DO_NOT_HONOR_SOFT",
                    "retryable": True,
                },
            )
            self._set_state(connection, mission_id, "recovering", 6)
            self._event(
                connection,
                mission_id,
                "recovery.started",
                "agent",
                "Recovering payment",
                "Done safely routed the payment to the backup provider.",
                payload={"strategy": "route_payment", "max_retries": 1},
            )
            self._event(
                connection,
                mission_id,
                "payment.rerouted",
                "agent",
                "Payment rerouted",
                "Payment was switched from PSP_A to PSP_B.",
                payload={"from_provider": "PSP_A", "to_provider": "PSP_B"},
            )
            self._record_payment(
                connection,
                mission_id,
                amount_cents,
                provider="PSP_B",
                status="authorized",
                retry_number=1,
                decline_code=None,
            )
            self._event(
                connection,
                mission_id,
                "payment.attempted",
                "payment",
                "Payment retry started",
                "PSP_B authorized the one permitted retry.",
                payload={"provider": "PSP_B", "attempt": 2, "amount": money(amount_cents)},
            )

        self._set_state(connection, mission_id, "executing", 6)
        self._event(
            connection,
            mission_id,
            "payment.authorized",
            "payment",
            "Payment authorized",
            "The simulated payment is complete.",
            payload={
                "provider": "PSP_B" if soft_failure is not None else "PSP_A",
                "amount": money(amount_cents),
            },
        )

        delivery = connection.execute(
            """
            SELECT d.* FROM delivery_options d
            JOIN baskets b ON b.delivery_option_id = d.id
            WHERE b.id = ?
            """,
            (basket["id"],),
        ).fetchone()
        assert delivery is not None
        order_id = new_id("ord")
        confirmation_code = f"DONE-{mission_id[-6:].upper()}"
        connection.execute(
            """
            INSERT INTO orders
                (id, mission_id, basket_id, confirmation_code, status,
                 total_cents, currency, delivery_at, created_at)
            VALUES (?, ?, ?, ?, 'confirmed', ?, 'PLN', ?, ?)
            """,
            (
                order_id,
                mission_id,
                basket["id"],
                confirmation_code,
                amount_cents,
                delivery["delivery_at"],
                utc_now(),
            ),
        )
        connection.execute(
            "UPDATE baskets SET status = 'ordered', updated_at = ? WHERE id = ?",
            (utc_now(), basket["id"]),
        )
        self._event(
            connection,
            mission_id,
            "order.confirmed",
            "merchant",
            "Order confirmed",
            f"Order {confirmation_code} will arrive before the deadline.",
            payload={
                "order_id": order_id,
                "confirmation_code": confirmation_code,
                "delivery_at": delivery["delivery_at"],
            },
        )

        recovery_count = connection.execute(
            """
            SELECT COUNT(*) AS count FROM failure_injections
            WHERE mission_id = ? AND status = 'consumed'
              AND failure_type IN ('product_unavailable', 'payment_soft_decline')
            """,
            (mission_id,),
        ).fetchone()["count"]
        completed_at = utc_now()
        summary = {
            "headline": "Everything is arranged",
            "description": "The party order is confirmed and both issues were fixed automatically.",
            "final_basket_cost": money(amount_cents),
            "budget_limit": money(mission["budget_limit_cents"]),
            "budget_remaining": money(mission["budget_limit_cents"] - amount_cents),
            "recovered_failures": recovery_count,
            "payment_attempts": 2 if soft_failure is not None else 1,
            "confirmation_code": confirmation_code,
            "delivery_at": delivery["delivery_at"],
        }
        connection.execute(
            """
            UPDATE missions
            SET status = 'completed', current_step = ?, completed_at = ?,
                summary_json = ?, updated_at = ?, revision = revision + 1
            WHERE id = ?
            """,
            (TOTAL_STEPS, completed_at, dump_json(summary), completed_at, mission_id),
        )
        self._event(
            connection,
            mission_id,
            "mission.completed",
            "agent",
            "Mission completed",
            "Order confirmed. One product and one payment failure were recovered automatically.",
            severity="success",
            payload=summary,
        )

    def _record_payment(
        self,
        connection: sqlite3.Connection,
        mission_id: str,
        amount_cents: int,
        provider: str,
        status: str,
        retry_number: int,
        decline_code: str | None,
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO payment_attempts
                (id, mission_id, merchant_id, amount_cents, currency, provider,
                 status, decline_code, retry_number, idempotency_key, created_at)
            VALUES (?, ?, 'merchant-b', ?, 'PLN', ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("pay"),
                mission_id,
                amount_cents,
                provider,
                status,
                decline_code,
                retry_number,
                f"{mission_id}:payment:{retry_number}",
                utc_now(),
            ),
        )

    def _validate_basket(
        self,
        connection: sqlite3.Connection,
        mission_id: str,
        basket_id: str,
        budget_limit_cents: int,
    ) -> None:
        basket = connection.execute(
            "SELECT * FROM baskets WHERE id = ?", (basket_id,)
        ).fetchone()
        if basket is None:
            raise WorkflowConflictError("Basket not found")
        contract_row = connection.execute(
            """
            SELECT * FROM mission_contracts
            WHERE mission_id = ? ORDER BY version DESC LIMIT 1
            """,
            (mission_id,),
        ).fetchone()
        if contract_row is None:
            raise WorkflowConflictError("Mission contract not found")
        delivery = connection.execute(
            """
            SELECT d.delivery_at, m.deadline FROM baskets b
            JOIN delivery_options d ON d.id = b.delivery_option_id
            JOIN missions m ON m.id = b.mission_id
            WHERE b.id = ? AND m.id = ?
            """,
            (basket_id, mission_id),
        ).fetchone()
        if delivery is None:
            raise WorkflowConflictError("Delivery selection not found")

        constraints: list[Constraint] = []
        for item in load_json(contract_row["hard_constraints_json"], []):
            raw_kind = item.get("type", "custom")
            try:
                kind = ConstraintKind(raw_kind)
            except ValueError:
                kind = ConstraintKind.CUSTOM
            constraints.append(
                Constraint(
                    kind=kind,
                    operator=str(item.get("operator", "equals")),
                    value=item.get("value", raw_kind),
                    hard=True,
                )
            )
        participant_items = load_json(contract_row["participants_json"], [])
        participant_count = int(participant_items[0].get("count", 1)) if participant_items else 1
        soft_preferences = tuple(
            str(item.get("type", item)) if isinstance(item, dict) else str(item)
            for item in load_json(contract_row["soft_preferences_json"], [])
        )
        contract = MissionContract(
            mission_id=mission_id,
            goal=contract_row["goal"],
            participants=participant_count,
            budget=Money(budget_limit_cents, contract_row["currency"]),
            deadline=datetime.fromisoformat(contract_row["deadline"]),
            hard_constraints=tuple(constraints),
            soft_preferences=soft_preferences,
            approval_policy=contract_row["approval_policy"],
            confidence=float(contract_row["confidence"]),
            version=int(contract_row["version"]),
        )
        item_rows = connection.execute(
            """
            SELECT bi.product_id, bi.quantity, bi.unit_price_cents,
                   p.category, p.allergens_json, p.tags_json
            FROM basket_items bi
            JOIN products p ON p.id = bi.product_id
            WHERE bi.basket_id = ?
            """,
            (basket_id,),
        ).fetchall()
        snapshot = BasketSnapshot(
            lines=tuple(
                BasketLine(
                    product_id=row["product_id"],
                    category=row["category"],
                    quantity=row["quantity"],
                    unit_price=Money(row["unit_price_cents"], basket["currency"]),
                    allergens=frozenset(load_json(row["allergens_json"], [])),
                    tags=frozenset(load_json(row["tags_json"], [])),
                )
                for row in item_rows
            ),
            delivery_cost=Money(basket["delivery_cost_cents"], basket["currency"]),
            delivery_at=datetime.fromisoformat(delivery["delivery_at"]),
        )
        decision = BasketPolicy().evaluate(contract, snapshot)
        if not decision.approved:
            violation = next(item for item in decision.violations if item.hard)
            raise WorkflowConflictError(violation.message)

    @staticmethod
    def _recalculate_basket(
        connection: sqlite3.Connection, basket_id: str
    ) -> tuple[int, int]:
        row = connection.execute(
            """
            SELECT COALESCE(SUM(quantity * unit_price_cents), 0) AS subtotal
            FROM basket_items WHERE basket_id = ?
            """,
            (basket_id,),
        ).fetchone()
        basket = connection.execute(
            "SELECT delivery_cost_cents FROM baskets WHERE id = ?", (basket_id,)
        ).fetchone()
        if basket is None:
            raise WorkflowConflictError("Basket not found")
        subtotal = row["subtotal"]
        total = subtotal + basket["delivery_cost_cents"]
        connection.execute(
            """
            UPDATE baskets
            SET subtotal_cents = ?, total_cents = ?, updated_at = ?
            WHERE id = ?
            """,
            (subtotal, total, utc_now(), basket_id),
        )
        return subtotal, total

    def _queue_failure(
        self,
        connection: sqlite3.Connection,
        mission_id: str,
        failure_type: str,
        payload: dict[str, Any],
    ) -> str:
        failure_id = new_id("fail")
        connection.execute(
            """
            INSERT INTO failure_injections
                (id, mission_id, failure_type, status, payload_json, created_at)
            VALUES (?, ?, ?, 'queued', ?, ?)
            """,
            (failure_id, mission_id, failure_type, dump_json(payload), utc_now()),
        )
        return failure_id

    @staticmethod
    def _safe_recovery_enabled(
        connection: sqlite3.Connection, mission_id: str
    ) -> bool:
        contract = connection.execute(
            """
            SELECT soft_preferences_json FROM mission_contracts
            WHERE mission_id = ? ORDER BY version DESC LIMIT 1
            """,
            (mission_id,),
        ).fetchone()
        if contract is None:
            return True
        for preference in load_json(contract["soft_preferences_json"], []):
            if isinstance(preference, dict) and preference.get("type") == "safe_recovery":
                return bool(preference.get("enabled", True))
        return True

    @staticmethod
    def _check_revision(mission: sqlite3.Row, expected_revision: int | None) -> None:
        if expected_revision is not None and mission["revision"] != expected_revision:
            raise WorkflowConflictError(
                f"Mission revision changed from {expected_revision} to {mission['revision']}"
            )

    def _replace_pending_approval(
        self,
        connection: sqlite3.Connection,
        mission_id: str,
        total_cents: int,
        *,
        reason: str,
        decision_id: str | None = None,
    ) -> str:
        pending = connection.execute(
            """
            SELECT * FROM approval_requests
            WHERE mission_id = ? AND status = 'pending'
            ORDER BY created_at DESC LIMIT 1
            """,
            (mission_id,),
        ).fetchone()
        now = utc_now()
        if pending is not None:
            connection.execute(
                """
                UPDATE approval_requests
                SET status = 'cancelled', selected_option = 'superseded', resolved_at = ?
                WHERE id = ?
                """,
                (now, pending["id"]),
            )
            self._event(
                connection,
                mission_id,
                "approval.superseded",
                "system",
                "Previous approval invalidated",
                reason,
                payload={"approval_id": pending["id"]},
            )
        if decision_id is None:
            decision = connection.execute(
                """
                SELECT id FROM portfolio_decisions
                WHERE mission_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (mission_id,),
            ).fetchone()
            decision_id = decision["id"] if decision is not None else None
        approval_id = new_id("apr")
        expires_at = (datetime.now(UTC) + timedelta(hours=2)).isoformat(timespec="seconds")
        connection.execute(
            """
            INSERT INTO approval_requests
                (id, mission_id, decision_id, approval_type, question, options_json,
                 status, expires_at, created_at)
            VALUES (?, ?, ?, 'purchase_approval', ?, ?, 'pending', ?, ?)
            """,
            (
                approval_id,
                mission_id,
                decision_id,
                f"Approve purchase for {money(total_cents):.2f} PLN?",
                dump_json(
                    [
                        {"id": "approve", "label": "Approve"},
                        {"id": "review", "label": "Review basket"},
                        {"id": "cancel", "label": "Cancel"},
                    ]
                ),
                expires_at,
                now,
            ),
        )
        self._event(
            connection,
            mission_id,
            "approval.requested",
            "agent",
            "Fresh approval required",
            f"Approve the updated purchase plan for {money(total_cents):.2f} PLN.",
            severity="action",
            payload={"approval_id": approval_id, "total": money(total_cents)},
        )
        return approval_id

    @staticmethod
    def _consume_failure(
        connection: sqlite3.Connection, mission_id: str, failure_type: str
    ) -> sqlite3.Row | None:
        row = connection.execute(
            """
            SELECT * FROM failure_injections
            WHERE mission_id = ? AND failure_type = ? AND status = 'queued'
            ORDER BY created_at ASC LIMIT 1
            """,
            (mission_id, failure_type),
        ).fetchone()
        if row is not None:
            connection.execute(
                """
                UPDATE failure_injections
                SET status = 'consumed', consumed_at = ?
                WHERE id = ?
                """,
                (utc_now(), row["id"]),
            )
        return row

    @staticmethod
    def _set_state(
        connection: sqlite3.Connection,
        mission_id: str,
        status: str,
        current_step: int,
    ) -> None:
        connection.execute(
            """
            UPDATE missions
            SET status = ?, current_step = ?, updated_at = ?, revision = revision + 1
            WHERE id = ?
            """,
            (status, current_step, utc_now(), mission_id),
        )

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        mission_id: str,
        event_type: str,
        actor: str,
        title: str,
        description: str,
        severity: str = "info",
        payload: dict[str, Any] | None = None,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO mission_events
                (mission_id, event_type, actor, title, description,
                 severity, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mission_id,
                event_type,
                actor,
                title,
                description,
                severity,
                dump_json(payload or {}),
                utc_now(),
            ),
        )
        return int(cursor.lastrowid)

    # ------------------------------------------------------------------
    # Response projections
    # ------------------------------------------------------------------
    def _detail(self, connection: sqlite3.Connection, mission_id: str) -> dict[str, Any]:
        mission = self._require_mission(connection, mission_id)
        contract = connection.execute(
            """
            SELECT * FROM mission_contracts
            WHERE mission_id = ? ORDER BY version DESC LIMIT 1
            """,
            (mission_id,),
        ).fetchone()
        basket = connection.execute(
            "SELECT * FROM baskets WHERE mission_id = ? ORDER BY created_at DESC LIMIT 1",
            (mission_id,),
        ).fetchone()
        approval = connection.execute(
            """
            SELECT * FROM approval_requests
            WHERE mission_id = ? ORDER BY created_at DESC LIMIT 1
            """,
            (mission_id,),
        ).fetchone()
        event_rows = connection.execute(
            "SELECT * FROM mission_events WHERE mission_id = ? ORDER BY id ASC",
            (mission_id,),
        ).fetchall()
        delivery_rows = connection.execute(
            """
            SELECT d.*, m.name AS merchant_name
            FROM delivery_options d JOIN merchants m ON m.id = d.merchant_id
            WHERE d.mission_id = ? ORDER BY d.selected DESC, d.confidence DESC
            """,
            (mission_id,),
        ).fetchall()
        payments = connection.execute(
            """
            SELECT * FROM payment_attempts
            WHERE mission_id = ? ORDER BY retry_number ASC
            """,
            (mission_id,),
        ).fetchall()
        order = connection.execute(
            "SELECT * FROM orders WHERE mission_id = ?", (mission_id,)
        ).fetchone()

        basket_projection = self._basket_projection(connection, basket) if basket else None
        metrics = self._metrics_projection(connection, mission, basket)
        return {
            "mission": self._mission_summary(connection, mission)
            | {
                "raw_voice_transcript": mission["raw_voice_transcript"],
                "input_mode": mission["input_mode"],
                "mission_type": mission["mission_type"],
                "budget_limit": money(mission["budget_limit_cents"]),
                "currency": mission["currency"],
                "deadline": mission["deadline"],
                "risk_level": mission["risk_level"],
                "requires_approval": bool(mission["requires_approval"]),
                "locale": mission["locale"],
                "timezone": mission["timezone"],
                "revision": mission["revision"],
            },
            "contract": self._contract_projection(contract) if contract else None,
            "basket": basket_projection,
            "approval": self._approval_projection(approval) if approval else None,
            "approvals": [self._approval_projection(approval)] if approval else [],
            "events": [self._event_projection(row) for row in event_rows],
            "metrics": metrics,
            "delivery_options": [self._delivery_projection(row) for row in delivery_rows],
            "payment_attempts": [self._payment_projection(row) for row in payments],
            "order": self._order_projection(order) if order else None,
            "summary": load_json(mission["summary_json"], None),
            "portfolio_decision": self.portfolio_planner.repository.latest_decision_projection(
                connection, mission_id
            ),
        }

    def _mission_summary(
        self, connection: sqlite3.Connection, mission: sqlite3.Row
    ) -> dict[str, Any]:
        latest = connection.execute(
            """
            SELECT title, description FROM mission_events
            WHERE mission_id = ? ORDER BY id DESC LIMIT 1
            """,
            (mission["id"],),
        ).fetchone()
        recovered_failures = connection.execute(
            """
            SELECT COUNT(*) AS count FROM failure_injections
            WHERE mission_id = ? AND status = 'consumed'
              AND failure_type IN ('product_unavailable', 'payment_soft_decline',
                                   'price_changed', 'delivery_slot_lost')
            """,
            (mission["id"],),
        ).fetchone()["count"]
        progress = round(
            min(1.0, max(0.0, mission["current_step"] / mission["total_steps"])), 2
        )
        return {
            "id": mission["id"],
            "title": mission["title"],
            "subtitle": mission["subtitle"],
            "status": mission["status"],
            "current_step": mission["current_step"],
            "total_steps": mission["total_steps"],
            "progress": progress,
            "latest_update": latest["description"] if latest else "Mission created.",
            "created_at": mission["created_at"],
            "completed_at": mission["completed_at"],
            "recovered_failures": recovered_failures,
        }

    def _basket_projection(
        self, connection: sqlite3.Connection, basket: sqlite3.Row
    ) -> dict[str, Any]:
        item_rows = connection.execute(
            """
            SELECT bi.*, p.name, p.description, p.category, p.currency,
                   p.allergens_json, p.tags_json, p.nut_free, p.image_url,
                   old.name AS replaced_product_name
            FROM basket_items bi
            JOIN products p ON p.id = bi.product_id
            LEFT JOIN products old ON old.id = bi.replaced_product_id
            WHERE bi.basket_id = ? ORDER BY p.category, p.name
            """,
            (basket["id"],),
        ).fetchall()
        merchant = connection.execute(
            "SELECT * FROM merchants WHERE id = ?", (basket["merchant_id"],)
        ).fetchone()
        items = [
            {
                "id": row["id"],
                "product_id": row["product_id"],
                "name": row["name"],
                "description": row["description"],
                "category": row["category"],
                "quantity": row["quantity"],
                "unit_price": money(row["unit_price_cents"]),
                "line_total": money(row["unit_price_cents"] * row["quantity"]),
                "currency": row["currency"],
                "allergens": load_json(row["allergens_json"], []),
                "tags": load_json(row["tags_json"], []),
                "nut_free": bool(row["nut_free"]),
                "substitution_allowed": bool(row["substitution_allowed"]),
                "replaced_product_id": row["replaced_product_id"],
                "replaced_product_name": row["replaced_product_name"],
                "image_url": row["image_url"],
            }
            for row in item_rows
        ]
        return {
            "id": basket["id"],
            "mission_id": basket["mission_id"],
            "merchant": (
                {
                    "id": merchant["id"],
                    "name": merchant["name"],
                    "reliability_score": merchant["reliability_score"],
                }
                if merchant
                else None
            ),
            "items": items,
            "item_count": sum(item["quantity"] for item in items),
            "subtotal": money(basket["subtotal_cents"]),
            "delivery_cost": money(basket["delivery_cost_cents"]),
            "total": money(basket["total_cents"]),
            "currency": basket["currency"],
            "status": basket["status"],
            "delivery_option_id": basket["delivery_option_id"],
        }

    def _metrics_projection(
        self,
        connection: sqlite3.Connection,
        mission: sqlite3.Row,
        basket: sqlite3.Row | None,
    ) -> dict[str, Any]:
        basket_total = basket["total_cents"] if basket else 0
        recovered = connection.execute(
            """
            SELECT COUNT(*) AS count FROM failure_injections
            WHERE mission_id = ? AND status = 'consumed'
              AND failure_type IN ('product_unavailable', 'payment_soft_decline',
                                   'price_changed', 'delivery_slot_lost')
            """,
            (mission["id"],),
        ).fetchone()["count"]
        payment_attempts = connection.execute(
            "SELECT COUNT(*) AS count FROM payment_attempts WHERE mission_id = ?",
            (mission["id"],),
        ).fetchone()["count"]
        return {
            "mission_completed": mission["status"] == "completed",
            "constraint_satisfaction_rate": 1.0,
            "recovered_failures": recovered,
            "human_interventions": 1 if mission["status"] == "completed" else 0,
            "final_basket_cost": money(basket_total),
            "budget_limit": money(mission["budget_limit_cents"]),
            "budget_variance": money(mission["budget_limit_cents"] - basket_total),
            "delivery_confidence": self._selected_delivery_confidence(
                connection, mission["id"]
            ),
            "payment_attempts": payment_attempts,
        }

    @staticmethod
    def _selected_delivery_confidence(
        connection: sqlite3.Connection, mission_id: str
    ) -> float:
        row = connection.execute(
            """
            SELECT confidence FROM delivery_options
            WHERE mission_id = ? AND selected = 1 LIMIT 1
            """,
            (mission_id,),
        ).fetchone()
        return float(row["confidence"]) if row else 0.0

    @staticmethod
    def _contract_projection(contract: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": contract["id"],
            "mission_id": contract["mission_id"],
            "goal": contract["goal"],
            "participants": load_json(contract["participants_json"], []),
            "needs": load_json(contract["needs_json"], []),
            "hard_constraints": load_json(contract["hard_constraints_json"], []),
            "soft_preferences": load_json(contract["soft_preferences_json"], []),
            "budget": {
                "limit": money(contract["budget_limit_cents"]),
                "currency": contract["currency"],
            },
            "budget_limit": money(contract["budget_limit_cents"]),
            "currency": contract["currency"],
            "deadline": contract["deadline"],
            "approval_policy": contract["approval_policy"],
            "allowed_categories": load_json(contract["allowed_categories_json"], []),
            "forbidden_categories": load_json(contract["forbidden_categories_json"], []),
            "confidence": contract["confidence"],
            "version": contract["version"],
        }

    @staticmethod
    def _approval_projection(approval: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": approval["id"],
            "mission_id": approval["mission_id"],
            "decision_id": approval["decision_id"],
            "type": approval["approval_type"],
            "approval_type": approval["approval_type"],
            "question": approval["question"],
            "options": load_json(approval["options_json"], []),
            "status": approval["status"],
            "selected_option": approval["selected_option"],
            "expires_at": approval["expires_at"],
            "created_at": approval["created_at"],
            "resolved_at": approval["resolved_at"],
        }

    @staticmethod
    def _event_projection(event: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": event["id"],
            "mission_id": event["mission_id"],
            "type": event["event_type"],
            "event_type": event["event_type"],
            "actor": event["actor"],
            "title": event["title"],
            "description": event["description"],
            "severity": event["severity"],
            "payload": load_json(event["payload_json"], {}),
            "created_at": event["created_at"],
        }

    @staticmethod
    def _delivery_projection(delivery: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": delivery["id"],
            "merchant_id": delivery["merchant_id"],
            "merchant_name": delivery["merchant_name"],
            "label": delivery["label"],
            "delivery_at": delivery["delivery_at"],
            "cost": money(delivery["cost_cents"]),
            "currency": "PLN",
            "confidence": delivery["confidence"],
            "selected": bool(delivery["selected"]),
            "available": bool(delivery["available"]),
        }

    @staticmethod
    def _payment_projection(payment: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": payment["id"],
            "provider": payment["provider"],
            "amount": money(payment["amount_cents"]),
            "currency": payment["currency"],
            "status": payment["status"],
            "decline_code": payment["decline_code"],
            "retry_number": payment["retry_number"],
            "created_at": payment["created_at"],
        }

    @staticmethod
    def _order_projection(order: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": order["id"],
            "confirmation_code": order["confirmation_code"],
            "status": order["status"],
            "total": money(order["total_cents"]),
            "currency": order["currency"],
            "delivery_at": order["delivery_at"],
            "created_at": order["created_at"],
        }

    @staticmethod
    def _failure_projection(
        failure: sqlite3.Row, already_queued: bool
    ) -> dict[str, Any]:
        return {
            "id": failure["id"],
            "mission_id": failure["mission_id"],
            "failure_type": failure["failure_type"],
            "status": failure["status"],
            "payload": load_json(failure["payload_json"], {}),
            "created_at": failure["created_at"],
            "already_queued": already_queued,
        }

    @staticmethod
    def _require_mission(
        connection: sqlite3.Connection, mission_id: str
    ) -> sqlite3.Row:
        mission = connection.execute(
            "SELECT * FROM missions WHERE id = ?", (mission_id,)
        ).fetchone()
        if mission is None:
            raise MissionNotFoundError(mission_id)
        return mission

    # ------------------------------------------------------------------
    # Deterministic intent interpretation
    # ------------------------------------------------------------------
    @staticmethod
    def _interpret(transcript: str, locale: str, timezone: str) -> dict[str, Any]:
        normalized = transcript.lower()
        budget_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:pln|zł|zl)\b", normalized)
        budget_cents = to_cents(budget_match.group(1)) if budget_match else 30_000
        participants = MissionWorkflow._extract_participants(normalized)
        deadline = MissionWorkflow._extract_deadline(normalized, timezone)
        deadline_local = datetime.fromisoformat(deadline)
        time_label = deadline_local.strftime("%H:%M")
        hard_constraints = [
            {
                "type": "budget",
                "operator": "less_than_or_equal",
                "value": money(budget_cents),
                "currency": "PLN",
            },
            {
                "type": "delivery_deadline",
                "operator": "before_or_at",
                "value": deadline,
            },
        ]
        # Nut-free is a non-relaxable safety default for the party demo fixture.
        hard_constraints.append(
            {"type": "allergen", "operator": "exclude", "value": "nuts"}
        )
        title = f"Birthday party for {participants} children"
        subtitle = (
            f"{participants} children · up to {money(budget_cents):.0f} PLN · "
            f"nut-free · by {time_label}"
        )
        return {
            "title": title,
            "subtitle": subtitle,
            "participants": participants,
            "budget_limit_cents": budget_cents,
            "deadline": deadline,
            "hard_constraints": hard_constraints,
            "confidence": 0.97 if budget_match else 0.88,
            "confirmation": (
                f"{participants} children, maximum {money(budget_cents):.0f} PLN, "
                f"no nuts, delivery before {time_label}. I’ll take care of it."
            ),
        }

    @staticmethod
    def _extract_participants(normalized: str) -> int:
        numeric = re.search(
            r"(?:for|dla|na)\s+(\d{1,3})\s+(?:children|kids|dzieci)", normalized
        )
        if numeric:
            return max(1, min(100, int(numeric.group(1))))
        number_words = {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
            "dziesięciorga": 10,
            "dziesieciorga": 10,
            "dziesięciu": 10,
            "dziesieciu": 10,
        }
        for word, count in number_words.items():
            if re.search(rf"\b{re.escape(word)}\s+(?:children|kids|dzieci)\b", normalized):
                return count
        return 10

    @staticmethod
    def _extract_deadline(normalized: str, timezone: str) -> str:
        try:
            zone = ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            zone = UTC
        local_now = datetime.now(zone)
        day_offset = 1 if re.search(r"\b(tomorrow|jutro)\b", normalized) else 0
        time_match = re.search(
            r"(?:before|by|do|przed)\s*(\d{1,2})(?::(\d{2}))?", normalized
        )
        hour = int(time_match.group(1)) if time_match else 16
        minute = int(time_match.group(2) or 0) if time_match else 0
        if hour > 23 or minute > 59:
            hour, minute = 16, 0
        deadline = (local_now + timedelta(days=day_offset)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if deadline <= local_now:
            deadline += timedelta(days=1)
        return deadline.isoformat()

    @staticmethod
    def _delivery_time(deadline: str, hours_before: int) -> str:
        return (datetime.fromisoformat(deadline) - timedelta(hours=hours_before)).isoformat()
