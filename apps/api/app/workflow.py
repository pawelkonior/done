"""Deterministic mission workflow and response projections.

The demo deliberately keeps the orchestration deterministic. The same service
boundary can later host a LangGraph runner, while policy checks, persistence,
approvals and commerce side effects remain unchanged.
"""

from __future__ import annotations

import json
import hashlib
import re
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.application.portfolio_planning_service import PortfolioPlanningService
from app.domain.common import Money
from app.domain.mission.catalog import (
    CatalogPlan,
    CatalogPlanNotFound,
    CatalogPlanningAgent,
    CatalogSearchRequest,
    ProductOffer,
)
from app.domain.mission.model import Constraint, ConstraintKind, MissionContract
from app.domain.mission.funding import (
    FundingContext,
    FundingGate,
    GuardrailAttestation,
    PlanFingerprint,
    ReservationSnapshot,
    UserApproval,
)
from app.domain.mission.intake import Occasion, MissionDraft, ShoppingScope, TranscriptInterpreter
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
    "clarification_required",
    "waiting_for_user",
    "waiting_for_support",
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
    def encode_domain_value(item: Any) -> Any:
        if isinstance(item, Decimal):
            # Draft evidence may contain the exact amount captured from the
            # transcript.  Preserve its decimal representation instead of
            # silently rounding it through a binary float.
            return format(item, "f")
        if hasattr(item, "isoformat"):
            return item.isoformat()
        if hasattr(item, "value"):
            return item.value
        raise TypeError(f"Object of type {type(item).__name__} is not JSON serializable")

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        default=encode_domain_value,
    )


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


def require_spoken_approval(
    transcript: str | None,
    *,
    amount_cents: int,
    currency: str,
    merchant_id: str,
) -> str:
    """Validate fail-closed spoken consent bound to the displayed total.

    Realtime tool arguments bind the immutable plan. This separate check makes
    the user evidence meaningful: it must be affirmative and repeat the amount
    and currency that were read aloud. Ambiguous or negated utterances require
    a fresh voice turn instead of starting commerce side effects.
    """

    spoken = (transcript or "").strip()
    normalized = spoken.casefold()
    if len(spoken) < 3:
        raise WorkflowConflictError(
            "A transcribed spoken approval is required"
        )
    if re.search(
        r"\b(?:nie|no|anuluj\w*|odrzuc\w*|reject\w*|cancel\w*|stop)\b",
        normalized,
    ):
        raise WorkflowConflictError(
            "Spoken approval was negative or ambiguous"
        )
    if re.search(
        r"\b(?:tak|yes|approve\w*|confirm\w*|agree\w*|"
        r"zatwierdz\w*|akcept\w*|potwierdz\w*|zgadzam)\b",
        normalized,
    ) is None:
        raise WorkflowConflictError(
            "Spoken approval must contain an explicit confirmation"
        )

    spoken_amounts: set[int] = set()
    for value in re.findall(r"(?<!\w)\d+(?:[\s.,]\d{1,2})?(?!\w)", normalized):
        compact = re.sub(r"\s+", "", value).replace(",", ".")
        try:
            spoken_amounts.add(to_cents(compact))
        except (ValueError, ArithmeticError):
            continue
    if amount_cents not in spoken_amounts:
        raise WorkflowConflictError(
            "Spoken approval amount does not match the current plan"
        )

    aliases = {
        "PLN": (r"\bpln\b", r"zł", r"zlot", r"złot"),
        "EUR": (r"\beur\b", r"€", r"euro"),
        "USD": (r"\busd\b", r"\$", r"dolar"),
    }
    if not any(re.search(alias, normalized) for alias in aliases.get(currency, ())):
        raise WorkflowConflictError(
            "Spoken approval currency does not match the current plan"
        )
    compact_spoken = re.sub(r"[^a-z0-9]+", "", normalized)
    compact_merchant = re.sub(r"[^a-z0-9]+", "", merchant_id.casefold())
    if not compact_merchant or compact_merchant not in compact_spoken:
        raise WorkflowConflictError(
            "Spoken approval merchant does not match the current plan"
        )
    return spoken[:4_000]


def normalize_failure_type(failure_type: str) -> str:
    return "product_unavailable" if failure_type == "out_of_stock" else failure_type


class MissionWorkflow:
    def __init__(
        self,
        database: Database,
        *,
        portfolio_planner: PortfolioPlanningService | None = None,
        commerce_mode: str = "demo",
    ):
        if commerce_mode not in {"demo", "sandbox", "live"}:
            raise ValueError("commerce_mode must be demo, sandbox, or live")
        self.database = database
        self.portfolio_planner = portfolio_planner or PortfolioPlanningService()
        self.commerce_mode = commerce_mode

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

    def _create_clarification_mission(
        self,
        *,
        transcript: str,
        locale: str,
        timezone: str,
        input_mode: str,
        interpreted: dict[str, Any],
        execution_policy: MissionExecutionPolicy,
        inject_demo_failures: bool,
        existing_mission_id: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """Persist an incomplete intake without inventing a purchase contract."""

        mission_id = existing_mission_id or new_id("mis")
        now = utc_now()
        placeholder_deadline = (datetime.now(UTC) + timedelta(days=365)).isoformat(
            timespec="seconds"
        )
        questions = list(interpreted.get("clarification_questions", []))
        question = questions[0] if questions else "Please add the missing mission details."
        with self.database.transaction() as connection:
            if existing_mission_id is None:
                connection.execute(
                    """
                    INSERT INTO missions
                        (id, user_id, title, subtitle, raw_voice_transcript, input_mode,
                         status, current_step, total_steps, mission_type,
                         budget_limit_cents, currency, deadline, risk_level,
                         requires_approval, locale, timezone, revision,
                         created_at, updated_at)
                    VALUES (?, 'demo-user', ?, ?, ?, ?, 'created', 1, ?, ?, ?, ?, ?,
                            100, 1, ?, ?, 1, ?, ?)
                    """,
                    (
                        mission_id,
                        interpreted["title"],
                        interpreted["subtitle"],
                        transcript,
                        input_mode,
                        TOTAL_STEPS,
                        interpreted.get("mission_type", "shopping"),
                        int(interpreted.get("budget_limit_cents") or 0),
                        interpreted.get("currency", "PLN"),
                        interpreted.get("deadline") or placeholder_deadline,
                        locale,
                        timezone,
                        now,
                        now,
                    ),
                )
            else:
                existing = self._require_mission(connection, mission_id)
                self._check_revision(existing, expected_revision)
                if existing["status"] != "clarification_required":
                    raise WorkflowConflictError("Mission is not awaiting clarification")
                connection.execute(
                    """
                    UPDATE missions
                    SET title = ?, subtitle = ?, raw_voice_transcript = ?,
                        input_mode = ?, mission_type = ?, budget_limit_cents = ?,
                        currency = ?, deadline = ?, risk_level = 100,
                        revision = revision + 1, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        interpreted["title"],
                        interpreted["subtitle"],
                        transcript,
                        input_mode,
                        interpreted.get("mission_type", "shopping"),
                        int(interpreted.get("budget_limit_cents") or 0),
                        interpreted.get("currency", "PLN"),
                        interpreted.get("deadline") or placeholder_deadline,
                        now,
                        mission_id,
                    ),
                )
                connection.execute(
                    "DELETE FROM mission_drafts WHERE mission_id = ?", (mission_id,)
                )
            connection.execute(
                """
                INSERT INTO mission_drafts
                    (mission_id, transcript, draft_json, execution_policy_json,
                     inject_demo_failures, version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    mission_id,
                    transcript,
                    dump_json(interpreted.get("draft", {})),
                    dump_json(
                        {
                            "approval_mode": execution_policy.approval_mode,
                            "approval_threshold_minor": (
                                execution_policy.approval_threshold.minor
                            ),
                            "approval_threshold_currency": (
                                execution_policy.approval_threshold.currency
                            ),
                            "safe_recovery_enabled": (
                                execution_policy.safe_recovery_enabled
                            ),
                            "preferred_merchant_ids": list(
                                execution_policy.preferred_merchant_ids
                            ),
                            "default_constraints": list(
                                execution_policy.default_constraints
                            ),
                        }
                    ),
                    int(inject_demo_failures),
                    now,
                    now,
                ),
            )
            if existing_mission_id is None:
                self._event(
                    connection,
                    mission_id,
                    "mission.created",
                    "system",
                    "Mission draft created",
                    "Done saved the request without inventing missing purchase details.",
                    payload={"input_mode": input_mode, "draft": True},
                )
                self._set_state(connection, mission_id, "understanding", 2)
            else:
                self._event(
                    connection,
                    mission_id,
                    "clarification.updated",
                    "user",
                    "Mission clarification received",
                    "Done re-evaluated the draft and still needs one or more details.",
                )
            self._event(
                connection,
                mission_id,
                "intent.needs_clarification",
                "agent",
                "More information is required",
                question,
                severity="action",
                payload={
                    "missing_information": interpreted.get("missing_information", []),
                    "ambiguities": interpreted.get("ambiguities", []),
                    "questions": questions,
                },
            )
            action_id = self._create_action_request(
                connection,
                mission_id,
                action_type="clarification",
                reason_code="MISSION_CONTRACT_INCOMPLETE",
                question=question,
                options=[
                    {"id": "answer_by_voice", "label": "Answer by voice"},
                    {"id": "request_human", "label": "Ask human support"},
                    {"id": "cancel", "label": "Cancel mission"},
                ],
                context={
                    "questions": questions,
                    "missing_information": interpreted.get("missing_information", []),
                    "ambiguities": interpreted.get("ambiguities", []),
                },
                expires_at=(datetime.now(UTC) + timedelta(days=7)).isoformat(
                    timespec="seconds"
                ),
            )
            connection.execute(
                """
                UPDATE action_requests
                SET question = ?, context_json = ?, expires_at = ?
                WHERE id = ?
                """,
                (
                    question,
                    dump_json(
                        {
                            "questions": questions,
                            "missing_information": interpreted.get(
                                "missing_information", []
                            ),
                            "ambiguities": interpreted.get("ambiguities", []),
                        }
                    ),
                    (datetime.now(UTC) + timedelta(days=7)).isoformat(
                        timespec="seconds"
                    ),
                    action_id,
                ),
            )
            if existing_mission_id is None:
                self._set_state(connection, mission_id, "clarification_required", 2)
            self._event(
                connection,
                mission_id,
                "action.requested",
                "system",
                "Voice clarification requested",
                question,
                severity="action",
                payload={"action_request_id": action_id},
            )
        return self.get_detail(mission_id)

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
        existing_mission_id: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        interpreted = interpretation or self._interpret(transcript, locale, timezone)
        policy = execution_policy or MissionExecutionPolicy()
        if not interpreted.get("ready_for_planning", True):
            return self._create_clarification_mission(
                transcript=transcript,
                locale=locale,
                timezone=timezone,
                input_mode=input_mode,
                interpreted=interpreted,
                execution_policy=policy,
                inject_demo_failures=inject_demo_failures,
                existing_mission_id=existing_mission_id,
                expected_revision=expected_revision,
            )
        mission_id = existing_mission_id or new_id("mis")
        contract_id = new_id("ctr")
        basket_id = new_id("bsk")
        approval_id = new_id("apr")
        selected_delivery_id = new_id("del")
        now = utc_now()
        shopping_scope = ShoppingScope(interpreted["shopping_scope"])
        portfolio_supported = shopping_scope == ShoppingScope.PARTY_SUPPLIES
        contract_needs = (
            needs_to_payload(
                party_needs(
                    interpreted["participants"],
                    include_candles=interpreted.get("recipient_age") is not None,
                    candle_quantity=max(
                        1,
                        (int(interpreted.get("recipient_age") or 1) + 9) // 10,
                    ),
                )
            )
            if portfolio_supported
            else []
        )

        with self.database.transaction() as connection:
            if existing_mission_id is None:
                connection.execute(
                    """
                    INSERT INTO missions
                        (id, user_id, title, subtitle, raw_voice_transcript, input_mode,
                         status, current_step, total_steps, mission_type,
                         budget_limit_cents, currency, deadline, risk_level,
                         requires_approval, locale, timezone, revision,
                         created_at, updated_at)
                    VALUES (?, 'demo-user', ?, ?, ?, ?, 'created', 1, ?,
                            ?, ?, ?, ?, 42, 1, ?, ?, 1, ?, ?)
                    """,
                    (
                        mission_id,
                        interpreted["title"],
                        interpreted["subtitle"],
                        transcript,
                        input_mode,
                        TOTAL_STEPS,
                        interpreted.get("mission_type", "party_shopping"),
                        interpreted["budget_limit_cents"],
                        interpreted.get("currency", "PLN"),
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
            else:
                existing = self._require_mission(connection, mission_id)
                self._check_revision(existing, expected_revision)
                if existing["status"] != "clarification_required":
                    raise WorkflowConflictError(
                        "Only a clarification draft can resume into planning"
                    )
                connection.execute(
                    """
                    UPDATE missions
                    SET title = ?, subtitle = ?, raw_voice_transcript = ?,
                        input_mode = ?, status = 'created', current_step = 1,
                        mission_type = ?, budget_limit_cents = ?, currency = ?,
                        deadline = ?, risk_level = 42, requires_approval = 1,
                        locale = ?, timezone = ?, revision = revision + 1,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        interpreted["title"],
                        interpreted["subtitle"],
                        transcript,
                        input_mode,
                        interpreted.get("mission_type", "party_shopping"),
                        interpreted["budget_limit_cents"],
                        interpreted.get("currency", "PLN"),
                        interpreted["deadline"],
                        locale,
                        timezone,
                        now,
                        mission_id,
                    ),
                )
                self._resolve_action_requests(
                    connection,
                    mission_id,
                    resolution={"reason": "clarification_answered"},
                    action_type="clarification",
                )
                connection.execute(
                    "DELETE FROM mission_drafts WHERE mission_id = ?", (mission_id,)
                )
                self._event(
                    connection,
                    mission_id,
                    "clarification.resolved",
                    "user",
                    "Mission details completed",
                    "The same mission can now continue to planning.",
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
                    "goal": interpreted.get("goal", "prepare_birthday_party"),
                    "confidence": interpreted["confidence"],
                    "missing_information": interpreted.get("missing_information", []),
                    "ambiguities": interpreted.get("ambiguities", []),
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    contract_id,
                    mission_id,
                    interpreted.get("goal", "prepare_birthday_party"),
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
                    interpreted.get("currency", "PLN"),
                    interpreted["deadline"],
                    policy.approval_mode,
                    dump_json(interpreted.get("allowed_categories", [])),
                    dump_json(interpreted.get("forbidden_categories", [])),
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
            delivery_reserve = Money(1299, interpreted["currency"])
            search_request = CatalogSearchRequest(
                scope=shopping_scope,
                participants=int(interpreted["participants"]),
                recipient_age=interpreted.get("recipient_age"),
                budget=Money(
                    int(interpreted["budget_limit_cents"]),
                    interpreted["currency"],
                ),
                delivery_reserve=delivery_reserve,
                allowed_categories=frozenset(
                    str(value).casefold()
                    for value in interpreted.get("allowed_categories", [])
                ),
                forbidden_categories=frozenset(
                    str(value).casefold()
                    for value in interpreted.get("forbidden_categories", [])
                ),
                hard_constraints=self._catalog_constraints(interpreted, policy),
                preferred_merchant_ids=policy.preferred_merchant_ids,
            )
            offers = self._load_catalog_offers(connection)
            try:
                catalog_plan = CatalogPlanningAgent().plan(search_request, offers)
            except CatalogPlanNotFound as exc:
                action_id = self._create_action_request(
                    connection,
                    mission_id,
                    action_type="search_recovery",
                    reason_code="NO_COMPLIANT_CATALOG_PLAN",
                    question=(
                        "Nie znalazłem jednego sprzedawcy z kompletnym koszykiem "
                        "spełniającym budżet i ograniczenia. Co mam zrobić dalej?"
                    ),
                    options=[
                        {"id": "request_human", "label": "Ask human support"},
                        {"id": "cancel", "label": "Cancel mission"},
                    ],
                    context={
                        "policy_failure": str(exc),
                        "shopping_scope": interpreted["shopping_scope"],
                        "currency": interpreted["currency"],
                    },
                )
                connection.execute(
                    "UPDATE missions SET requires_approval = 0 WHERE id = ?",
                    (mission_id,),
                )
                self._set_state(connection, mission_id, "waiting_for_user", 3)
                self._event(
                    connection,
                    mission_id,
                    "catalog.plan_not_found",
                    "agent",
                    "No compliant catalog plan found",
                    "The mission is paused before approval, reservation or funding.",
                    severity="action",
                    payload={
                        "reason": str(exc),
                        "action_request_id": action_id,
                        "card_created": False,
                    },
                )
                return self._detail(connection, mission_id)

            planned_products = self._catalog_plan_products(
                connection,
                catalog_plan,
            )
            planned_categories = sorted(
                {str(product["category"]) for product in planned_products.values()}
            )
            self._event(
                connection,
                mission_id,
                "plan.created",
                "agent",
                "Shopping plan created",
                (
                    f"Done planned {sum(line.quantity for line in catalog_plan.lines)} "
                    f"items across {len(planned_categories)} catalog categories."
                ),
                payload={
                    "categories": planned_categories,
                    "estimated_items": sum(
                        line.quantity for line in catalog_plan.lines
                    ),
                },
            )
            self._set_state(connection, mission_id, "searching", 3)
            self._event(
                connection,
                mission_id,
                "catalog.searched",
                "tool",
                "Catalog searched",
                "Found a complete, constraint-safe basket from one merchant.",
                payload={
                    "merchant_id": catalog_plan.merchant_id,
                    "candidates_considered": catalog_plan.candidates_considered,
                    "preferred_merchant_ids": list(policy.preferred_merchant_ids),
                    "preferred_match": (
                        catalog_plan.merchant_id in policy.preferred_merchant_ids
                    ),
                    "shopping_scope": interpreted["shopping_scope"],
                },
            )

            decision = None
            if portfolio_supported:
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
                    payload={
                        "snapshot_id": decision.snapshot_id,
                        "decision_id": decision.id,
                    },
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
                        payload={
                            "need_ids": [action.need_id for action in orange_actions]
                        },
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
                        payload={
                            "decision_id": decision.id,
                            "reasons": list(decision.constraint_report),
                        },
                    )
                    self._set_state(connection, mission_id, "failed", 4)
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
                        payload={
                            "decision_id": decision.id,
                            "reasons": list(decision.constraint_report),
                        },
                    )
                    self._set_state(connection, mission_id, "failed", 4)
                    return self._detail(connection, mission_id)
                if decision.status is PortfolioDecisionStatus.WAITING:
                    self._event(
                        connection,
                        mission_id,
                        "portfolio.waiting",
                        "solver",
                        "Waiting for a safer price point",
                        "The selected offers can safely wait until their latest point to buy.",
                        payload={
                            "decision_id": decision.id,
                            "reasons": list(decision.explanations),
                        },
                    )
                    self._set_state(connection, mission_id, "waiting", 4)
                    return self._detail(connection, mission_id)

                catalog_signature = sorted(
                    (
                        line.product_id,
                        line.quantity,
                        int(planned_products[line.product_id]["price_cents"]),
                    )
                    for line in catalog_plan.lines
                )
                decision_signature = sorted(
                    (
                        action.offer.product_id,
                        action.quantity,
                        action.offer.price_cents,
                    )
                    for action in decision.selected_actions
                    if action.action.value == "buy_now"
                )
                if (
                    decision.selected_merchant_id != catalog_plan.merchant_id
                    or decision_signature != catalog_signature
                ):
                    action_id = self._create_action_request(
                        connection,
                        mission_id,
                        action_type="human_support",
                        reason_code="PLANNERS_DISAGREE",
                        question=(
                            "Catalog and portfolio planners produced different checkout "
                            "plans. Review them before asking the user for approval."
                        ),
                        options=[{"id": "cancel", "label": "Cancel mission"}],
                        context={
                            "portfolio_decision_id": decision.id,
                            "catalog_merchant_id": catalog_plan.merchant_id,
                            "portfolio_merchant_id": decision.selected_merchant_id,
                        },
                        owner="support",
                    )
                    self._set_state(connection, mission_id, "waiting_for_support", 4)
                    connection.execute(
                        "UPDATE missions SET requires_approval = 0 WHERE id = ?",
                        (mission_id,),
                    )
                    self._event(
                        connection,
                        mission_id,
                        "portfolio.catalog_mismatch",
                        "policy",
                        "Checkout planners disagree",
                        "No basket, approval, reservation, card or payment was created.",
                        severity="action",
                        payload={
                            "action_request_id": action_id,
                            "decision_id": decision.id,
                        },
                    )
                    return self._detail(connection, mission_id)

            delivery_at = self._delivery_time(interpreted["deadline"], hours_before=2)
            selected_delivery_cost = delivery_reserve.minor
            delivery_options = (
                (
                    selected_delivery_id,
                    mission_id,
                    catalog_plan.merchant_id,
                    "Priority delivery",
                    delivery_at,
                    selected_delivery_cost,
                    0.96,
                    1,
                    1,
                ),
                (
                    new_id("del"),
                    mission_id,
                    catalog_plan.merchant_id,
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
                    catalog_plan.merchant_id,
                    "Early backup slot",
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
                VALUES (?, ?, ?, ?, 0, ?, ?, ?, 'proposed', ?, ?)
                """,
                (
                    basket_id,
                    mission_id,
                    catalog_plan.merchant_id,
                    selected_delivery_id,
                    selected_delivery_cost,
                    selected_delivery_cost,
                    interpreted["currency"],
                    now,
                    now,
                ),
            )
            for line in catalog_plan.lines:
                product = planned_products[line.product_id]
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
                        line.product_id,
                        line.quantity,
                        product["price_cents"],
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
                (
                    f"Selected {len(catalog_plan.lines)} products for "
                    f"{money(total):.2f} {interpreted['currency']}."
                ),
                payload={
                    "basket_id": basket_id,
                    "decision_id": decision.id if decision is not None else None,
                    "subtotal": money(subtotal),
                    "delivery_cost": money(selected_delivery_cost),
                    "total": money(total),
                    "currency": interpreted["currency"],
                },
            )

            self._set_state(connection, mission_id, "validating", 4)
            try:
                self._validate_basket(
                    connection,
                    mission_id,
                    basket_id,
                    interpreted["budget_limit_cents"],
                )
            except WorkflowConflictError as exc:
                action_id = self._create_action_request(
                    connection,
                    mission_id,
                    action_type="search_recovery",
                    reason_code="NO_COMPLIANT_PLAN",
                    question=(
                        "Nie znalazłem jeszcze koszyka spełniającego wszystkie "
                        "ograniczenia. Czy przekazać wyszukiwanie człowiekowi?"
                    ),
                    options=[
                        {"id": "request_human", "label": "Ask human support"},
                        {"id": "cancel", "label": "Cancel mission"},
                    ],
                    context={"policy_failure": str(exc)},
                )
                self._set_state(connection, mission_id, "waiting_for_user", 4)
                connection.execute(
                    """
                    UPDATE missions SET requires_approval = 0 WHERE id = ?
                    """,
                    (mission_id,),
                )
                connection.execute(
                    """
                    UPDATE baskets SET status = 'intervention_required', updated_at = ?
                    WHERE id = ?
                    """,
                    (utc_now(), basket_id),
                )
                self._event(
                    connection,
                    mission_id,
                    "policy.plan_blocked",
                    "policy",
                    "No compliant plan found",
                    "Funding is blocked and the mission is waiting for a safe next step.",
                    severity="action",
                    payload={
                        "reason": str(exc),
                        "action_request_id": action_id,
                        "card_created": False,
                    },
                )
                return self._detail(connection, mission_id)
            approval_required = policy.requires_approval(
                Money(total, interpreted["currency"]), risk_level=42
            )
            self._event(
                connection,
                mission_id,
                "policy.validated",
                "policy",
                "All constraints satisfied",
                "The basket is within budget and deliverable before the deadline; all explicit hard constraints pass.",
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
                failure_product_id = self._substitutable_basket_product(
                    connection,
                    basket_id,
                )
                if failure_product_id is not None:
                    self._queue_failure(
                        connection,
                        mission_id,
                        "product_unavailable",
                        {"product_id": failure_product_id},
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
                        decision.id if decision is not None else None,
                        (
                            f"Approve purchase for {money(total):.2f} "
                            f"{interpreted['currency']}?"
                        ),
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
                self._bind_approval_evidence(
                    connection,
                    approval_id,
                    mission_id,
                )
                self._set_state(connection, mission_id, "approval_required", 5)
                self._event(
                    connection,
                    mission_id,
                    "approval.requested",
                    "agent",
                    "Ready for approval",
                    (
                        f"Approve the complete basket for {money(total):.2f} "
                        f"{interpreted['currency']}."
                    ),
                    severity="action",
                    payload={
                        "approval_id": approval_id,
                        "total": money(total),
                        "currency": interpreted["currency"],
                    },
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

        return self.get_detail(mission_id)

    def resolve_approval(
        self,
        approval_id: str,
        choice: str,
        voice_transcript: str | None = None,
        expected_revision: int | None = None,
        expected_amount: float | None = None,
        expected_currency: str | None = None,
        expected_plan_hash: str | None = None,
        expected_merchant_id: str | None = None,
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            approval = connection.execute(
                "SELECT * FROM approval_requests WHERE id = ?", (approval_id,)
            ).fetchone()
            if approval is None:
                raise ApprovalNotFoundError(approval_id)
            mission_id = approval["mission_id"]
            mission = self._require_mission(connection, mission_id)
            if expected_revision is None:
                raise WorkflowConflictError(
                    "Approval resolution requires the exact mission revision"
                )
            if choice == "approve" and any(
                value is None
                for value in (
                    expected_amount,
                    expected_currency,
                    expected_plan_hash,
                    expected_merchant_id,
                )
            ):
                raise WorkflowConflictError(
                    "Approval must bind amount, currency, plan and merchant"
                )
            if choice == "approve":
                voice_transcript = require_spoken_approval(
                    voice_transcript,
                    amount_cents=to_cents(expected_amount or 0),
                    currency=expected_currency or "",
                    merchant_id=expected_merchant_id or "",
                )

            if approval["status"] != "pending":
                # Same-choice retries are safe and return the already materialized result.
                if approval["selected_option"] == choice:
                    if choice == "approve":
                        evidence = connection.execute(
                            "SELECT * FROM approval_evidence WHERE approval_id = ?",
                            (approval_id,),
                        ).fetchone()
                        if evidence is None or (
                            to_cents(expected_amount or 0) != evidence["amount_cents"]
                            or expected_currency != evidence["currency"]
                            or expected_plan_hash != evidence["plan_hash"]
                            or expected_merchant_id != evidence["merchant_id"]
                        ):
                            raise WorkflowConflictError(
                                "Approval retry does not match its immutable evidence"
                            )
                    return self._detail(connection, mission_id)
                raise WorkflowConflictError("Approval has already been resolved")

            self._check_revision(mission, expected_revision)

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
                basket = connection.execute(
                    "SELECT total_cents FROM baskets WHERE mission_id = ? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (mission_id,),
                ).fetchone()
                if basket is None:
                    raise WorkflowConflictError("Mission has no basket")
                fresh_id = self._replace_pending_approval(
                    connection,
                    mission_id,
                    basket["total_cents"],
                    reason="The previous approval expired before execution.",
                )
                self._set_state(connection, mission_id, "approval_required", 5)
                self._event(
                    connection,
                    mission_id,
                    "approval.refreshed_after_expiry",
                    "policy",
                    "Fresh approval is ready",
                    "The expired approval was persisted and no commerce side effect started.",
                    severity="action",
                    payload={"old_approval_id": approval_id, "approval_id": fresh_id},
                )
                return self._detail(connection, mission_id)

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

            if choice == "approve":
                evidence = connection.execute(
                    "SELECT * FROM approval_evidence WHERE approval_id = ?",
                    (approval_id,),
                ).fetchone()
                basket = connection.execute(
                    "SELECT * FROM baskets WHERE mission_id = ? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (mission_id,),
                ).fetchone()
                if basket is None:
                    raise WorkflowConflictError("Mission has no basket")
                try:
                    # Provider/catalog metadata may have changed after the
                    # approval was presented. Re-run every hard guardrail
                    # before comparing or accepting consent.
                    self._validate_basket(
                        connection,
                        mission_id,
                        basket["id"],
                        mission["budget_limit_cents"],
                    )
                except WorkflowConflictError as exc:
                    connection.execute(
                        """
                        UPDATE approval_requests
                        SET status = 'cancelled', selected_option = 'policy_changed',
                            resolved_at = ?
                        WHERE id = ?
                        """,
                        (utc_now(), approval_id),
                    )
                    action_id = self._create_action_request(
                        connection,
                        mission_id,
                        action_type="search_recovery",
                        reason_code="PLAN_NO_LONGER_COMPLIANT",
                        question=(
                            "The approved plan no longer satisfies every guardrail. "
                            "Ask human support for a fresh plan?"
                        ),
                        options=[
                            {"id": "request_human", "label": "Ask human support"},
                            {"id": "cancel", "label": "Cancel mission"},
                        ],
                        context={"policy_failure": str(exc)},
                    )
                    self._set_state(connection, mission_id, "waiting_for_user", 5)
                    connection.execute(
                        "UPDATE baskets SET status = 'intervention_required', updated_at = ? "
                        "WHERE id = ?",
                        (utc_now(), basket["id"]),
                    )
                    self._event(
                        connection,
                        mission_id,
                        "approval.rejected_policy_change",
                        "policy",
                        "Plan no longer passes guardrails",
                        "No reservation, card request or payment was started.",
                        severity="action",
                        payload={
                            "approval_id": approval_id,
                            "action_request_id": action_id,
                            "reason": str(exc),
                        },
                    )
                    return self._detail(connection, mission_id)
                current_plan = self._current_plan_fingerprint(connection, mission_id)
                if evidence is None:
                    # Consent cannot be reconstructed after the fact. Present
                    # a newly bound approval and leave every commerce side
                    # effect untouched.
                    fresh_id = self._replace_pending_approval(
                        connection,
                        mission_id,
                        current_plan.all_in_total.minor,
                        reason=(
                            "The approval had no immutable plan evidence and must be "
                            "presented again."
                        ),
                    )
                    self._set_state(connection, mission_id, "approval_required", 5)
                    self._event(
                        connection,
                        mission_id,
                        "approval.rejected_missing_evidence",
                        "policy",
                        "Approval evidence was missing",
                        "No reservation, card request or payment was started.",
                        severity="action",
                        payload={"old_approval_id": approval_id, "approval_id": fresh_id},
                    )
                    return self._detail(connection, mission_id)
                if (
                    evidence["plan_hash"] != current_plan.plan_hash
                    or evidence["merchant_id"] != current_plan.merchant_id
                    or evidence["amount_cents"] != current_plan.all_in_total.minor
                    or evidence["currency"] != current_plan.currency
                ):
                    connection.execute(
                        """
                        UPDATE approval_requests
                        SET status = 'cancelled', selected_option = 'stale_plan',
                            resolved_at = ?
                        WHERE id = ?
                        """,
                        (utc_now(), approval_id),
                    )
                    fresh_id = self._replace_pending_approval(
                        connection,
                        mission_id,
                        current_plan.all_in_total.minor,
                        reason="The plan changed before approval and must be reviewed again.",
                    )
                    self._set_state(connection, mission_id, "approval_required", 5)
                    self._event(
                        connection,
                        mission_id,
                        "approval.rejected_stale_plan",
                        "policy",
                        "Approval did not match the current plan",
                        "No execution or funding side effect was started.",
                        severity="action",
                        payload={"old_approval_id": approval_id, "approval_id": fresh_id},
                    )
                    return self._detail(connection, mission_id)
                if to_cents(expected_amount or 0) != current_plan.all_in_total.minor:
                    raise WorkflowConflictError(
                        "Spoken approval amount does not match the current plan"
                    )
                if expected_currency != current_plan.currency:
                    raise WorkflowConflictError(
                        "Spoken approval currency does not match the current plan"
                    )
                if expected_plan_hash != current_plan.plan_hash:
                    raise WorkflowConflictError(
                        "Spoken approval plan does not match the current plan"
                    )
                if expected_merchant_id != current_plan.merchant_id:
                    raise WorkflowConflictError(
                        "Spoken approval merchant does not match the current plan"
                    )

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

            basket = connection.execute(
                "SELECT id FROM baskets WHERE mission_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (mission_id,),
            ).fetchone()
            product_id = (
                self._first_basket_product(connection, basket["id"])
                if basket is not None
                else None
            )
            substitutable_product_id = (
                self._substitutable_basket_product(connection, basket["id"])
                if basket is not None
                else None
            )
            if failure_type == "product_unavailable" and substitutable_product_id is None:
                raise WorkflowConflictError(
                    "Current basket has no safely substitutable line to inject"
                )
            if failure_type == "price_changed" and product_id is None:
                raise WorkflowConflictError("Current mission has no basket line to inject")
            defaults: dict[str, dict[str, Any]] = {
                "product_unavailable": {"product_id": substitutable_product_id},
                "price_changed": {
                    "product_id": product_id,
                    "increase_percent": 20,
                },
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

    def resolve_action_request(
        self,
        action_request_id: str,
        choice: str,
        *,
        voice_transcript: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """Resolve or escalate one durable human-in-the-loop request."""

        with self.database.reader() as connection:
            action = connection.execute(
                "SELECT * FROM action_requests WHERE id = ?", (action_request_id,)
            ).fetchone()
            if action is None:
                raise WorkflowConflictError("Action request was not found")
            mission = self._require_mission(connection, action["mission_id"])
            self._check_revision(mission, expected_revision)
            if action["owner"] != "user":
                raise WorkflowConflictError(
                    "This action request is assigned to human support"
                )
            options = {
                str(item.get("id"))
                for item in load_json(action["options_json"], [])
                if isinstance(item, dict) and item.get("id")
            }
            if action["status"] != "pending":
                resolution = load_json(action["resolution_json"], {})
                if resolution.get("choice") == choice:
                    return self.get_detail(action["mission_id"])
                raise WorkflowConflictError("Action request has already been resolved")
            if choice not in options:
                raise WorkflowConflictError("Choice is not allowed for this action request")
            mission_id = action["mission_id"]

        if choice == "answer_by_voice":
            if voice_transcript is None or len(voice_transcript.strip()) < 3:
                raise WorkflowConflictError("A spoken clarification is required")
            # Recheck status, option and expiry under the write lock.  The
            # subsequent correction is revision-bound, closing the small gap
            # between this transaction and the aggregate update.
            with self.database.transaction() as connection:
                action = connection.execute(
                    "SELECT * FROM action_requests WHERE id = ?",
                    (action_request_id,),
                ).fetchone()
                if action is None:
                    raise WorkflowConflictError("Action request was not found")
                mission = self._require_mission(connection, action["mission_id"])
                self._check_revision(mission, expected_revision)
                if action["owner"] != "user":
                    raise WorkflowConflictError(
                        "This action request is assigned to human support"
                    )
                options = {
                    str(item.get("id"))
                    for item in load_json(action["options_json"], [])
                    if isinstance(item, dict) and item.get("id")
                }
                if action["status"] != "pending":
                    raise WorkflowConflictError("Action request has already been resolved")
                if choice not in options:
                    raise WorkflowConflictError(
                        "Choice is not allowed for this action request"
                    )
                if action["expires_at"] and datetime.fromisoformat(
                    action["expires_at"]
                ) <= datetime.now(UTC):
                    self._refresh_expired_action(connection, action)
                    return self._detail(connection, mission_id)
                correction_revision = int(mission["revision"])
            return self.apply_correction(
                mission_id,
                voice_transcript,
                expected_revision=correction_revision,
            )

        with self.database.transaction() as connection:
            action = connection.execute(
                "SELECT * FROM action_requests WHERE id = ?", (action_request_id,)
            ).fetchone()
            assert action is not None
            mission = self._require_mission(connection, mission_id)
            self._check_revision(mission, expected_revision)
            if action["owner"] != "user":
                raise WorkflowConflictError(
                    "This action request is assigned to human support"
                )
            if action["status"] != "pending":
                resolution = load_json(action["resolution_json"], {})
                if resolution.get("choice") == choice:
                    return self._detail(connection, mission_id)
                raise WorkflowConflictError("Action request has already been resolved")
            options = {
                str(item.get("id"))
                for item in load_json(action["options_json"], [])
                if isinstance(item, dict) and item.get("id")
            }
            if choice not in options:
                raise WorkflowConflictError("Choice is not allowed for this action request")
            if action["expires_at"] and datetime.fromisoformat(
                action["expires_at"]
            ) <= datetime.now(UTC):
                self._refresh_expired_action(connection, action)
                return self._detail(connection, mission_id)
            connection.execute(
                """
                UPDATE action_requests
                SET status = 'resolved', resolved_at = ?, resolution_json = ?
                WHERE id = ?
                """,
                (
                    utc_now(),
                    dump_json({"choice": choice, "voice_transcript": voice_transcript}),
                    action_request_id,
                ),
            )

            if choice == "cancel":
                self._set_state(connection, mission_id, "cancelled", mission["current_step"])
                connection.execute(
                    "UPDATE baskets SET status = 'cancelled', updated_at = ? "
                    "WHERE mission_id = ?",
                    (utc_now(), mission_id),
                )
                connection.execute(
                    "UPDATE approval_requests SET status = 'cancelled', "
                    "selected_option = 'cancel', resolved_at = ? "
                    "WHERE mission_id = ? AND status = 'pending'",
                    (utc_now(), mission_id),
                )
                self._event(
                    connection,
                    mission_id,
                    "action.cancelled_mission",
                    "user",
                    "Mission cancelled",
                    "The user cancelled from a voice action request.",
                )
                return self._detail(connection, mission_id)

            if choice == "request_human":
                support_id = self._create_action_request(
                    connection,
                    mission_id,
                    action_type="human_support",
                    reason_code="HUMAN_REVIEW_REQUESTED",
                    question="Review the blocked mission and propose a compliant next step.",
                    options=[
                        {"id": "resume", "label": "Resume with a compliant plan"},
                        {"id": "cancel", "label": "Cancel mission"},
                    ],
                    context={
                        "source_action_request_id": action_request_id,
                        "user_choice": choice,
                        "source_context": load_json(action["context_json"], {}),
                    },
                    owner="support",
                )
                self._set_state(connection, mission_id, "waiting_for_support", 6)
                self._event(
                    connection,
                    mission_id,
                    "support.requested",
                    "user",
                    "Human support requested",
                    "The mission remains paused; no hard constraint was relaxed.",
                    severity="action",
                    payload={"action_request_id": support_id},
                )
                return self._detail(connection, mission_id)

            # Review or payment-method changes remain a user-owned pause. No
            # execution is resumed implicitly from a generic action choice.
            follow_up_id = self._create_action_request(
                connection,
                mission_id,
                action_type="user_follow_up",
                reason_code="USER_FOLLOW_UP_REQUIRED",
                question="Complete the requested review, then approve the refreshed plan.",
                options=[
                    {"id": "request_human", "label": "Ask human support"},
                    {"id": "cancel", "label": "Cancel mission"},
                ],
                context={"previous_choice": choice},
            )
            self._set_state(connection, mission_id, "waiting_for_user", 6)
            self._event(
                connection,
                mission_id,
                "action.follow_up_required",
                "system",
                "One user step remains",
                "Funding and checkout remain blocked.",
                severity="action",
                payload={"action_request_id": follow_up_id},
            )
            return self._detail(connection, mission_id)

    def request_human_support(
        self,
        mission_id: str,
        *,
        reason: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            mission = self._require_mission(connection, mission_id)
            self._check_revision(mission, expected_revision)
            if mission["status"] in {"completed", "cancelled"}:
                raise WorkflowConflictError("A terminal mission cannot be escalated")
            action_id = self._create_action_request(
                connection,
                mission_id,
                action_type="human_support",
                reason_code="USER_REQUESTED_SUPPORT",
                question="Review this mission and contact the user with compliant options.",
                options=[
                    {"id": "resume", "label": "Resume with a compliant plan"},
                    {"id": "cancel", "label": "Cancel mission"},
                ],
                context={"reason": (reason or "").strip()[:500]},
                owner="support",
            )
            self._set_state(
                connection,
                mission_id,
                "waiting_for_support",
                mission["current_step"],
            )
            self._event(
                connection,
                mission_id,
                "support.requested",
                "user",
                "Human support requested",
                "The mission is paused until a human proposes a safe next step.",
                severity="action",
                payload={"action_request_id": action_id},
            )
            return self._detail(connection, mission_id)

    def cancel_mission(
        self,
        mission_id: str,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            mission = self._require_mission(connection, mission_id)
            self._check_revision(mission, expected_revision)
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
            self._resolve_action_requests(
                connection,
                mission_id,
                resolution={"choice": "cancel", "source": "mission_cancelled"},
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
                    "Delivery option is not compatible with the selected checkout merchant; "
                    "changing delivery merchants requires a full basket re-plan"
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
                (
                    f"Selected {option['label']} for "
                    f"{money(option['cost_cents']):.2f} {basket['currency']}."
                ),
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
        with self.database.reader() as connection:
            draft_mission = self._require_mission(connection, mission_id)
            if draft_mission["status"] == "clarification_required":
                self._check_revision(draft_mission, expected_revision)
                draft_row = connection.execute(
                    "SELECT * FROM mission_drafts WHERE mission_id = ?",
                    (mission_id,),
                ).fetchone()
                if draft_row is None:
                    raise WorkflowConflictError("Clarification mission has no saved draft")
                combined_transcript = (
                    f"{draft_row['transcript']}\nClarification: {correction}"
                )
                interpreted = self._interpret(
                    combined_transcript,
                    draft_mission["locale"],
                    draft_mission["timezone"],
                )
                raw_policy = load_json(draft_row["execution_policy_json"], {})
                policy = MissionExecutionPolicy(
                    approval_mode=raw_policy.get("approval_mode", "always"),
                    approval_threshold=Money(
                        int(raw_policy.get("approval_threshold_minor", 0)),
                        raw_policy.get("approval_threshold_currency", "PLN"),
                    ),
                    safe_recovery_enabled=bool(
                        raw_policy.get("safe_recovery_enabled", True)
                    ),
                    preferred_merchant_ids=tuple(
                        raw_policy.get("preferred_merchant_ids", [])
                    ),
                    default_constraints=tuple(raw_policy.get("default_constraints", [])),
                )
                inject_demo_failures = bool(draft_row["inject_demo_failures"])
                input_mode = draft_mission["input_mode"]
                locale = draft_mission["locale"]
                timezone = draft_mission["timezone"]
                current_revision = int(draft_mission["revision"])
            else:
                draft_row = None
        if draft_row is not None:
            return self.create_mission(
                transcript=combined_transcript,
                locale=locale,
                timezone=timezone,
                input_mode=input_mode,
                interpretation=interpreted,
                inject_demo_failures=inject_demo_failures,
                execution_policy=policy,
                existing_mission_id=mission_id,
                expected_revision=current_revision,
            )
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
            contract_needs = load_json(contract["needs_json"], [])
            if not contract_needs:
                raise WorkflowConflictError(
                    "Gift mission corrections require a fresh catalog planning run"
                )

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
                include_candles = any(
                    isinstance(need, dict) and need.get("id") == "candles"
                    for need in contract_needs
                )
                candle_quantity = next(
                    (
                        int(need.get("quantity", 1))
                        for need in contract_needs
                        if isinstance(need, dict) and need.get("id") == "candles"
                    ),
                    1,
                )
                needs_json = dump_json(
                    needs_to_payload(
                        party_needs(
                            participant_count,
                            include_candles=include_candles,
                            candle_quantity=candle_quantity,
                        )
                    )
                )

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
            contract = connection.execute(
                "SELECT needs_json FROM mission_contracts "
                "WHERE mission_id = ? ORDER BY version DESC LIMIT 1",
                (mission_id,),
            ).fetchone()
            if contract is None:
                raise WorkflowConflictError("Mission has no contract")
            if not load_json(contract["needs_json"], []):
                raise WorkflowConflictError(
                    "Portfolio re-planning is not available for gift missions"
                )
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
            conditions.append(
                "(status IN ('approval_required', 'clarification_required', "
                "'waiting_for_user', 'waiting_for_support') OR EXISTS ("
                "SELECT 1 FROM action_requests ar "
                "WHERE ar.mission_id = missions.id AND ar.status = 'pending'))"
            )
        elif requires_action is False:
            conditions.append(
                "(status NOT IN ('approval_required', 'clarification_required', "
                "'waiting_for_user', 'waiting_for_support') AND NOT EXISTS ("
                "SELECT 1 FROM action_requests ar "
                "WHERE ar.mission_id = missions.id AND ar.status = 'pending'))"
            )
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
            "SELECT * FROM baskets WHERE mission_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (mission_id,),
        ).fetchone()
        if basket is None:
            raise WorkflowConflictError("Mission has no basket")

        current_plan = self._current_plan_fingerprint(connection, mission_id)
        approved_plan = connection.execute(
            """
            SELECT ae.plan_hash FROM approval_requests ar
            JOIN approval_evidence ae ON ae.approval_id = ar.id
            WHERE ar.mission_id = ? AND ar.status = 'approved'
            ORDER BY ar.resolved_at DESC LIMIT 1
            """,
            (mission_id,),
        ).fetchone()
        if approved_plan is None or approved_plan["plan_hash"] != current_plan.plan_hash:
            self._replace_pending_approval(
                connection,
                mission_id,
                basket["total_cents"],
                reason=(
                    "Funding requires an explicit approval bound to the exact current plan."
                ),
            )
            connection.execute(
                """
                UPDATE missions
                SET status = 'approval_required', current_step = 5,
                    requires_approval = 1, revision = revision + 1, updated_at = ?
                WHERE id = ?
                """,
                (utc_now(), mission_id),
            )
            self._event(
                connection,
                mission_id,
                "funding.approval_required",
                "policy",
                "Exact plan approval required",
                "No inventory, card or payment side effect was started.",
                severity="action",
                payload={"plan_hash": current_plan.plan_hash},
            )
            return

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
                action_id = self._create_action_request(
                    connection,
                    mission_id,
                    action_type="recovery_decision",
                    reason_code="AUTOMATIC_RECOVERY_DISABLED",
                    question="Automatic recovery is disabled. What should Done do next?",
                    options=[
                        {"id": "request_human", "label": "Ask human support"},
                        {"id": "cancel", "label": "Cancel mission"},
                    ],
                    context={"failure_type": blocked_failure["failure_type"]},
                )
                self._set_state(connection, mission_id, "waiting_for_user", 6)
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
                    "mission.action_required",
                    "system",
                    "Mission needs manual intervention",
                    "The mission is safely paused and can resume after your decision.",
                    severity="action",
                    payload={"action_request_id": action_id},
                )
                return

        if self.commerce_mode == "live":
            action_id = self._create_action_request(
                connection,
                mission_id,
                action_type="human_support",
                reason_code="MERCHANT_AND_CARD_PROVIDERS_NOT_CONFIGURED",
                question=(
                    "Connect a merchant reservation provider and card issuer before "
                    "this live purchase can continue."
                ),
                options=[{"id": "cancel", "label": "Cancel mission"}],
                context={"plan_hash": current_plan.plan_hash},
                owner="support",
            )
            self._set_state(connection, mission_id, "waiting_for_support", 6)
            self._event(
                connection,
                mission_id,
                "commerce.providers_required",
                "system",
                "Live commerce providers are not configured",
                "No synthetic reservation, card request or payment was created.",
                severity="action",
                payload={"action_request_id": action_id},
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
            action_id = self._create_action_request(
                connection,
                mission_id,
                action_type="recovery_decision",
                reason_code="PRICE_QUOTE_CHANGED",
                question=(
                    "The merchant price changed before reservation. Ask human support "
                    "for a fresh compliant quote?"
                ),
                options=[
                    {"id": "request_human", "label": "Ask human support"},
                    {"id": "cancel", "label": "Cancel mission"},
                ],
                context=load_json(price_failure["payload_json"], {}),
            )
            self._set_state(connection, mission_id, "waiting_for_user", 6)
            connection.execute(
                "UPDATE baskets SET status = 'intervention_required', updated_at = ? "
                "WHERE id = ?",
                (utc_now(), basket["id"]),
            )
            self._event(
                connection,
                mission_id,
                "price.changed",
                "merchant",
                "Price changed",
                "A selected product became more expensive during checkout.",
                severity="warning",
                payload={
                    **load_json(price_failure["payload_json"], {}),
                    "action_request_id": action_id,
                },
            )
            self._event(
                connection,
                mission_id,
                "recovery.started",
                "agent",
                "Fresh quote required",
                "Execution stopped; no unreserved price was treated as guaranteed.",
                severity="action",
                payload={"strategy": "request_fresh_quote"},
            )
            return

        inventory_failure = self._consume_failure(
            connection, mission_id, "product_unavailable"
        )
        if inventory_failure is not None:
            injected_payload = load_json(inventory_failure["payload_json"], {})
            injected_product_id = injected_payload.get("product_id")
            planned_line = (
                connection.execute(
                    "SELECT id FROM basket_items WHERE basket_id = ? AND product_id = ?",
                    (basket["id"], injected_product_id),
                ).fetchone()
                if isinstance(injected_product_id, str)
                else None
            )
            if planned_line is None:
                self._event(
                    connection,
                    mission_id,
                    "failure.injection_skipped",
                    "system",
                    "Synthetic inventory failure skipped",
                    "The injected product is not part of the current planned basket.",
                    severity="warning",
                    payload={"failure_type": "product_unavailable"},
                )
                inventory_failure = None
        if inventory_failure is not None:
            payload = load_json(inventory_failure["payload_json"], {})
            unavailable_id = payload["product_id"]
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
                "Done searched the same merchant for a contract-compatible substitute.",
                payload={"strategy": "replace_product"},
            )
            basket_item = connection.execute(
                """
                SELECT * FROM basket_items
                WHERE basket_id = ? AND product_id = ?
                """,
                (basket["id"], unavailable_id),
            ).fetchone()
            if basket_item is None:
                raise WorkflowConflictError("Unavailable product is not in the basket")
            replacement = connection.execute(
                """
                SELECT * FROM products
                WHERE id != ? AND merchant_id = ? AND substitute_group = ?
                  AND category = ? AND currency = ? AND allergens_json = ?
                  AND stock >= ?
                ORDER BY rating DESC, price_cents ASC
                LIMIT 1
                """,
                (
                    unavailable_id,
                    unavailable["merchant_id"],
                    unavailable["substitute_group"],
                    unavailable["category"],
                    unavailable["currency"],
                    unavailable["allergens_json"],
                    basket_item["quantity"],
                ),
            ).fetchone()
            if replacement is None:
                action_id = self._create_action_request(
                    connection,
                    mission_id,
                    action_type="recovery_decision",
                    reason_code="NO_COMPLIANT_REPLACEMENT",
                    question=(
                        f"{unavailable['name']} is unavailable and no safe replacement "
                        "was found. What should Done do next?"
                    ),
                    options=[
                        {"id": "request_human", "label": "Ask human support"},
                        {"id": "cancel", "label": "Cancel mission"},
                    ],
                    context={
                        "product_id": unavailable_id,
                        "hard_constraints_preserved": True,
                    },
                )
                self._set_state(connection, mission_id, "waiting_for_user", 6)
                connection.execute(
                    "UPDATE baskets SET status = 'intervention_required', updated_at = ? "
                    "WHERE id = ?",
                    (utc_now(), basket["id"]),
                )
                self._event(
                    connection,
                    mission_id,
                    "recovery.action_required",
                    "agent",
                    "No safe replacement found",
                    "The mission is paused without relaxing any hard constraint.",
                    severity="action",
                    payload={"action_request_id": action_id},
                )
                return
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
                "The replacement preserves every explicit constraint, budget and delivery.",
                payload={"approved": True, "violations": [], "constraint_score": 1.0},
            )
            self._replace_pending_approval(
                connection,
                mission_id,
                total,
                reason="A product changed, so the updated plan requires fresh approval.",
            )
            connection.execute(
                """
                UPDATE missions
                SET status = 'approval_required', current_step = 5,
                    requires_approval = 1, revision = revision + 1, updated_at = ?
                WHERE id = ?
                """,
                (utc_now(), mission_id),
            )
            return

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
                  AND merchant_id = ? AND delivery_at <= ?
                ORDER BY confidence DESC LIMIT 1
                """,
                (mission_id, basket["merchant_id"], mission["deadline"]),
            ).fetchone()
            if selected is None or backup is None:
                action_id = self._create_action_request(
                    connection,
                    mission_id,
                    action_type="recovery_decision",
                    reason_code="DELIVERY_UNAVAILABLE",
                    question=(
                        "No delivery option still satisfies the deadline. "
                        "Would you like human support to look for another merchant?"
                    ),
                    options=[
                        {"id": "request_human", "label": "Ask human support"},
                        {"id": "cancel", "label": "Cancel mission"},
                    ],
                    context={"failure_type": "delivery_slot_lost"},
                )
                self._set_state(connection, mission_id, "waiting_for_user", 6)
                connection.execute(
                    "UPDATE baskets SET status = 'intervention_required', updated_at = ? "
                    "WHERE id = ?",
                    (utc_now(), basket["id"]),
                )
                self._event(
                    connection,
                    mission_id,
                    "recovery.action_required",
                    "agent",
                    "Delivery needs a decision",
                    "No compliant backup delivery slot is currently available.",
                    severity="action",
                    payload={"action_request_id": action_id},
                )
                return

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
            _, changed_total = self._recalculate_basket(connection, basket["id"])
            self._validate_basket(
                connection,
                mission_id,
                basket["id"],
                mission["budget_limit_cents"],
            )
            self._event(
                connection,
                mission_id,
                "delivery.switched",
                "agent",
                "Delivery slot recovered",
                f"Done found a compliant backup: {backup['label']}.",
                payload={
                    "old_option_id": selected["id"],
                    "new_option_id": backup["id"],
                    "new_total": money(changed_total),
                    "requires_fresh_approval": True,
                },
            )
            # A delivery, merchant or amount mutation invalidates the approval.
            # Stop before any payment side effect and bind a fresh approval to
            # the newly validated basket.
            self._replace_pending_approval(
                connection,
                mission_id,
                changed_total,
                reason="Delivery changed after approval, so a fresh approval is required.",
            )
            connection.execute(
                """
                UPDATE missions
                SET status = 'approval_required', current_step = 5,
                    requires_approval = 1, revision = revision + 1, updated_at = ?
                WHERE id = ?
                """,
                (utc_now(), mission_id),
            )
            return

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

        reservation = self._reserve_current_plan(connection, mission_id)
        if not self._prepare_virtual_card_request(connection, mission_id, reservation):
            return

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
            action_id = self._create_action_request(
                connection,
                mission_id,
                action_type="payment_decision",
                reason_code="PAYMENT_METHOD_DECLINED",
                question="The payment method was declined. How should Done continue?",
                options=[
                    {"id": "change_payment_method", "label": "Use another payment method"},
                    {"id": "request_human", "label": "Ask human support"},
                    {"id": "cancel", "label": "Cancel mission"},
                ],
                context={"decline_code": "LOST_CARD", "retryable": False},
            )
            self._set_state(connection, mission_id, "waiting_for_user", 6)
            connection.execute(
                "UPDATE baskets SET status = 'payment_failed', updated_at = ? WHERE id = ?",
                (utc_now(), basket["id"]),
            )
            connection.execute(
                "UPDATE virtual_card_requests SET status = 'closed_declined' "
                "WHERE mission_id = ? AND status IN ('sandbox_ready', 'demo_spec')",
                (mission_id,),
            )
            self._event(
                connection,
                mission_id,
                "mission.action_required",
                "system",
                "Mission needs a new payment method",
                "No automatic retry was made after the hard decline.",
                severity="action",
                payload={"action_request_id": action_id},
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
        connection.execute(
            "UPDATE virtual_card_requests SET status = 'used_closed' "
            "WHERE mission_id = ? AND status IN ('sandbox_ready', 'demo_spec')",
            (mission_id,),
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
            VALUES (?, ?, ?, ?, 'confirmed', ?, ?, ?, ?)
            """,
            (
                order_id,
                mission_id,
                basket["id"],
                confirmation_code,
                amount_cents,
                current_basket["currency"],
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
            "description": (
                "The shopping order is confirmed. "
                f"Recovered issues: {recovery_count}."
            ),
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
            f"Order confirmed. Recovered issues: {recovery_count}.",
            severity="success",
            payload=summary,
        )

    def _current_plan_fingerprint(
        self,
        connection: sqlite3.Connection,
        mission_id: str,
    ) -> PlanFingerprint:
        basket = connection.execute(
            "SELECT * FROM baskets WHERE mission_id = ? ORDER BY created_at DESC LIMIT 1",
            (mission_id,),
        ).fetchone()
        if basket is None:
            raise WorkflowConflictError("Mission has no basket to fingerprint")
        contract = connection.execute(
            """
            SELECT * FROM mission_contracts
            WHERE mission_id = ? ORDER BY version DESC LIMIT 1
            """,
            (mission_id,),
        ).fetchone()
        if contract is None:
            raise WorkflowConflictError("Mission has no contract to fingerprint")
        delivery = connection.execute(
            "SELECT * FROM delivery_options WHERE id = ?",
            (basket["delivery_option_id"],),
        ).fetchone()
        if delivery is None:
            raise WorkflowConflictError("Mission has no delivery to fingerprint")
        if delivery["merchant_id"] != basket["merchant_id"]:
            raise WorkflowConflictError(
                "Delivery merchant does not match the basket merchant"
            )
        if not delivery["available"] or not delivery["selected"]:
            raise WorkflowConflictError("Selected delivery is no longer available")
        items = connection.execute(
            """
            SELECT bi.product_id, bi.quantity, bi.unit_price_cents,
                   bi.substitution_allowed, p.merchant_id, p.category,
                   p.currency AS catalog_currency, p.stock,
                   p.allergens_json, p.tags_json
            FROM basket_items bi
            JOIN products p ON p.id = bi.product_id
            WHERE bi.basket_id = ?
            ORDER BY bi.product_id, bi.quantity, bi.unit_price_cents
            """,
            (basket["id"],),
        ).fetchall()
        canonical_items = [
            {
                "product_id": item["product_id"],
                "merchant_id": item["merchant_id"],
                "category": item["category"],
                "quantity": int(item["quantity"]),
                "unit_price_cents": int(item["unit_price_cents"]),
                "currency": item["catalog_currency"],
                "available_stock": int(item["stock"]),
                "allergens": sorted(load_json(item["allergens_json"], [])),
                "tags": sorted(load_json(item["tags_json"], [])),
                "substitution_allowed": bool(item["substitution_allowed"]),
            }
            for item in items
        ]
        canonical = {
            "mission_id": mission_id,
            "contract_version": int(contract["version"]),
            "contract": {
                "goal": contract["goal"],
                "participants": load_json(contract["participants_json"], []),
                "hard_constraints": load_json(contract["hard_constraints_json"], []),
                "soft_preferences": load_json(contract["soft_preferences_json"], []),
                "budget_limit_cents": int(contract["budget_limit_cents"]),
                "currency": contract["currency"],
                "deadline": contract["deadline"],
                "approval_policy": contract["approval_policy"],
                "allowed_categories": load_json(contract["allowed_categories_json"], []),
                "forbidden_categories": load_json(contract["forbidden_categories_json"], []),
            },
            "basket": {
                "merchant_id": basket["merchant_id"],
                "delivery_option_id": basket["delivery_option_id"],
                "delivery": {
                    "merchant_id": delivery["merchant_id"],
                    "delivery_at": delivery["delivery_at"],
                    "cost_cents": int(delivery["cost_cents"]),
                    "available": bool(delivery["available"]),
                    "selected": bool(delivery["selected"]),
                },
                "delivery_cost_cents": int(basket["delivery_cost_cents"]),
                "total_cents": int(basket["total_cents"]),
                "currency": basket["currency"],
                "items": canonical_items,
            },
        }
        serialized = json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return PlanFingerprint(
            mission_id=mission_id,
            plan_hash=f"sha256:{hashlib.sha256(serialized).hexdigest()}",
            merchant_id=basket["merchant_id"],
            all_in_total=Money(int(basket["total_cents"]), basket["currency"]),
        )

    def _record_guardrail_attestation(
        self,
        connection: sqlite3.Connection,
        mission_id: str,
        *,
        checks: list[str],
    ) -> PlanFingerprint:
        plan = self._current_plan_fingerprint(connection, mission_id)
        attested_at = datetime.now(UTC)
        expires_at = attested_at + timedelta(minutes=10)
        connection.execute(
            """
            INSERT INTO guardrail_attestations
                (id, mission_id, plan_hash, passed, evidence_json,
                 attested_at, expires_at)
            VALUES (?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT(mission_id, plan_hash) DO UPDATE SET
                passed = 1,
                evidence_json = excluded.evidence_json,
                attested_at = excluded.attested_at,
                expires_at = excluded.expires_at
            """,
            (
                new_id("grd"),
                mission_id,
                plan.plan_hash,
                dump_json({"ruleset_version": 1, "checks": checks}),
                attested_at.isoformat(timespec="milliseconds"),
                expires_at.isoformat(timespec="milliseconds"),
            ),
        )
        return plan

    def _bind_approval_evidence(
        self,
        connection: sqlite3.Connection,
        approval_id: str,
        mission_id: str,
    ) -> PlanFingerprint:
        plan = self._current_plan_fingerprint(connection, mission_id)
        connection.execute(
            """
            INSERT INTO approval_evidence
                (approval_id, mission_id, plan_hash, merchant_id,
                 amount_cents, currency, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                approval_id,
                mission_id,
                plan.plan_hash,
                plan.merchant_id,
                plan.all_in_total.minor,
                plan.currency,
                utc_now(),
            ),
        )
        return plan

    def _reserve_current_plan(
        self,
        connection: sqlite3.Connection,
        mission_id: str,
    ) -> ReservationSnapshot:
        plan = self._current_plan_fingerprint(connection, mission_id)
        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=5)
        connection.execute(
            "UPDATE inventory_reservations SET status = 'superseded' "
            "WHERE mission_id = ? AND status = 'valid'",
            (mission_id,),
        )
        connection.execute(
            """
            INSERT INTO inventory_reservations
                (id, mission_id, plan_hash, merchant_id, amount_cents,
                 currency, status, provider, reserved_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, 'valid', ?, ?, ?)
            """,
            (
                new_id("res"),
                mission_id,
                plan.plan_hash,
                plan.merchant_id,
                plan.all_in_total.minor,
                plan.currency,
                self.commerce_mode,
                now.isoformat(timespec="milliseconds"),
                expires_at.isoformat(timespec="milliseconds"),
            ),
        )
        return ReservationSnapshot(
            plan=plan,
            valid=True,
            reserved_at=now,
            expires_at=expires_at,
        )

    def _prepare_virtual_card_request(
        self,
        connection: sqlite3.Connection,
        mission_id: str,
        reservation: ReservationSnapshot,
    ) -> bool:
        plan = self._current_plan_fingerprint(connection, mission_id)
        mission = self._require_mission(connection, mission_id)
        approval = connection.execute(
            """
            SELECT ar.resolved_at, ar.expires_at, ae.*
            FROM approval_requests ar
            JOIN approval_evidence ae ON ae.approval_id = ar.id
            WHERE ar.mission_id = ? AND ar.status = 'approved'
            ORDER BY ar.resolved_at DESC LIMIT 1
            """,
            (mission_id,),
        ).fetchone()
        guardrails = connection.execute(
            """
            SELECT * FROM guardrail_attestations
            WHERE mission_id = ? AND plan_hash = ? AND passed = 1
            ORDER BY attested_at DESC LIMIT 1
            """,
            (mission_id, plan.plan_hash),
        ).fetchone()
        unresolved = connection.execute(
            "SELECT id FROM action_requests WHERE mission_id = ? AND status = 'pending'",
            (mission_id,),
        ).fetchall()
        context = FundingContext(
            checkout=plan,
            budget=Money(mission["budget_limit_cents"], mission["currency"]),
            guardrails=(
                GuardrailAttestation(
                    plan=plan,
                    passed=bool(guardrails["passed"]),
                    attested_at=datetime.fromisoformat(guardrails["attested_at"]),
                    expires_at=datetime.fromisoformat(guardrails["expires_at"]),
                )
                if guardrails is not None
                else None
            ),
            approval=(
                UserApproval(
                    plan=PlanFingerprint(
                        mission_id=mission_id,
                        plan_hash=approval["plan_hash"],
                        merchant_id=approval["merchant_id"],
                        all_in_total=Money(approval["amount_cents"], approval["currency"]),
                    ),
                    approved=True,
                    approved_amount=Money(approval["amount_cents"], approval["currency"]),
                    approved_at=datetime.fromisoformat(approval["resolved_at"]),
                    expires_at=datetime.fromisoformat(approval["expires_at"]),
                )
                if approval is not None
                else None
            ),
            reservation=reservation,
            unresolved_actions=tuple(row["id"] for row in unresolved),
            idempotency_key=f"fund:{mission_id}:{plan.plan_hash}",
        )
        decision = FundingGate().evaluate(context, now=datetime.now(UTC))
        if not decision.approved or decision.card_spec is None:
            codes = [violation.code.value for violation in decision.violations]
            action_id = self._create_action_request(
                connection,
                mission_id,
                action_type="funding_decision",
                reason_code="FUNDING_GATE_BLOCKED",
                question="Funding is blocked until the approved plan is validated again.",
                options=[
                    {"id": "review", "label": "Review the latest plan"},
                    {"id": "request_human", "label": "Ask human support"},
                    {"id": "cancel", "label": "Cancel mission"},
                ],
                context={"violations": codes, "plan_hash": plan.plan_hash},
            )
            self._set_state(connection, mission_id, "waiting_for_user", 6)
            self._event(
                connection,
                mission_id,
                "funding.blocked",
                "policy",
                "Funding gate blocked the card",
                "No card request or payment was created.",
                severity="action",
                payload={"action_request_id": action_id, "violations": codes},
            )
            return False

        if self.commerce_mode == "live":
            action_id = self._create_action_request(
                connection,
                mission_id,
                action_type="human_support",
                reason_code="CARD_ISSUER_NOT_CONFIGURED",
                question="A card issuer must be connected before this live purchase can continue.",
                options=[{"id": "cancel", "label": "Cancel mission"}],
                context={"plan_hash": plan.plan_hash},
                owner="support",
            )
            self._set_state(connection, mission_id, "waiting_for_support", 6)
            self._event(
                connection,
                mission_id,
                "funding.issuer_required",
                "system",
                "Card issuer not configured",
                "The live workflow stopped before exposing or creating card credentials.",
                severity="action",
                payload={"action_request_id": action_id},
            )
            return False

        spec = decision.card_spec
        existing_request = connection.execute(
            "SELECT * FROM virtual_card_requests WHERE idempotency_key = ?",
            (spec.idempotency_key,),
        ).fetchone()
        if existing_request is not None:
            action_id = self._create_action_request(
                connection,
                mission_id,
                action_type="funding_decision",
                reason_code="FUNDING_ATTEMPT_ALREADY_EXISTS",
                question="A previous funding attempt exists and requires review.",
                options=[
                    {"id": "request_human", "label": "Ask human support"},
                    {"id": "cancel", "label": "Cancel mission"},
                ],
                context={
                    "plan_hash": spec.plan_hash,
                    "existing_status": existing_request["status"],
                },
            )
            self._set_state(connection, mission_id, "waiting_for_user", 6)
            self._event(
                connection,
                mission_id,
                "funding.reentry_blocked",
                "policy",
                "Funding attempt cannot be reused",
                "A closed, expired or existing card request never re-enters payment.",
                severity="action",
                payload={"action_request_id": action_id},
            )
            return False
        connection.execute(
            """
            INSERT INTO virtual_card_requests
                (id, mission_id, plan_hash, merchant_lock, max_amount_cents,
                 currency, status, restrictions_json, idempotency_key,
                 created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("vcr"),
                mission_id,
                spec.plan_hash,
                spec.merchant_lock,
                spec.max_amount.minor,
                spec.currency,
                "sandbox_ready" if self.commerce_mode == "sandbox" else "demo_spec",
                dump_json(
                    {
                        "single_use": spec.single_use,
                        "no_cash": spec.no_cash,
                        "no_recurring": spec.no_recurring,
                    }
                ),
                spec.idempotency_key,
                spec.issued_at.isoformat(timespec="milliseconds"),
                spec.expires_at.isoformat(timespec="milliseconds"),
            ),
        )
        self._event(
            connection,
            mission_id,
            "funding.card_request_ready",
            "policy",
            "Restricted card request is ready",
            "The request was created only after matching guardrails, approval and reservation.",
            payload={
                "plan_hash": spec.plan_hash,
                "merchant_lock": spec.merchant_lock,
                "max_amount": money(spec.max_amount.minor),
                "currency": spec.currency,
                "mode": self.commerce_mode,
                "contains_card_secrets": False,
            },
        )
        return True

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
        basket = connection.execute(
            "SELECT merchant_id, currency FROM baskets "
            "WHERE mission_id = ? ORDER BY created_at DESC LIMIT 1",
            (mission_id,),
        ).fetchone()
        if basket is None:
            raise WorkflowConflictError("Mission has no basket for payment")
        idempotency_key = f"{mission_id}:payment:{retry_number}"
        existing = connection.execute(
            "SELECT id FROM payment_attempts WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing is not None:
            raise WorkflowConflictError("Payment attempt was already recorded")
        connection.execute(
            """
            INSERT INTO payment_attempts
                (id, mission_id, merchant_id, amount_cents, currency, provider,
                 status, decline_code, retry_number, idempotency_key, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("pay"),
                mission_id,
                basket["merchant_id"],
                amount_cents,
                basket["currency"],
                provider,
                status,
                decline_code,
                retry_number,
                idempotency_key,
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
            SELECT d.delivery_at, d.merchant_id AS delivery_merchant_id,
                   d.available AS delivery_available, d.selected AS delivery_selected,
                   b.merchant_id AS basket_merchant_id, m.deadline
            FROM baskets b
            JOIN delivery_options d ON d.id = b.delivery_option_id
            JOIN missions m ON m.id = b.mission_id
            WHERE b.id = ? AND m.id = ?
            """,
            (basket_id, mission_id),
        ).fetchone()
        if delivery is None:
            raise WorkflowConflictError("Delivery selection not found")
        if delivery["delivery_merchant_id"] != delivery["basket_merchant_id"]:
            raise WorkflowConflictError(
                "Delivery merchant does not match the basket merchant"
            )
        if not delivery["delivery_available"] or not delivery["delivery_selected"]:
            raise WorkflowConflictError("Selected delivery is no longer available")

        constraints: list[Constraint] = []
        for item in load_json(contract_row["hard_constraints_json"], []):
            raw_kind = item.get("type", "custom")
            try:
                kind = ConstraintKind(raw_kind)
            except ValueError:
                kind = ConstraintKind.CUSTOM
                item = {
                    "operator": "unsupported",
                    "value": f"unknown_kind:{raw_kind}",
                }
            operator = str(item.get("operator", "equals"))
            value = item.get("value", raw_kind)
            if kind == ConstraintKind.BUDGET:
                currency = str(item.get("currency", contract_row["currency"]))
                if (
                    operator != "less_than_or_equal"
                    or currency != contract_row["currency"]
                    or to_cents(value) != int(contract_row["budget_limit_cents"])
                ):
                    raise WorkflowConflictError(
                        "Budget guardrail does not match the mission contract"
                    )
            elif kind == ConstraintKind.DEADLINE:
                try:
                    constrained_deadline = datetime.fromisoformat(str(value))
                except ValueError as exc:
                    raise WorkflowConflictError(
                        "Delivery deadline guardrail is invalid"
                    ) from exc
                if (
                    operator != "before_or_at"
                    or constrained_deadline
                    != datetime.fromisoformat(contract_row["deadline"])
                ):
                    raise WorkflowConflictError(
                        "Delivery deadline guardrail does not match the contract"
                    )
            constraints.append(
                Constraint(
                    kind=kind,
                    operator=operator,
                    value=value,
                    hard=True,
                )
            )
        existing_prohibited = {
            str(item.value).casefold()
            for item in constraints
            if item.kind == ConstraintKind.PROHIBITED_CATEGORY
        }
        for category in load_json(contract_row["forbidden_categories_json"], []):
            if str(category).casefold() not in existing_prohibited:
                constraints.append(
                    Constraint(
                        ConstraintKind.PROHIBITED_CATEGORY,
                        "exclude",
                        str(category),
                    )
                )

        # User profile defaults are part of the immutable contract snapshot.
        # Translate the small supported vocabulary and fail closed on anything
        # the policy engine cannot prove.
        default_values: list[str] = []
        for preference in load_json(contract_row["soft_preferences_json"], []):
            if (
                isinstance(preference, dict)
                and preference.get("type") == "user_default_constraints"
            ):
                default_values.extend(str(value) for value in preference.get("values", []))
        for raw_default in default_values:
            normalized = raw_default.casefold()
            if "nut" in normalized or "orzech" in normalized:
                constraints.append(
                    Constraint(ConstraintKind.ALLERGEN, "exclude", "nuts")
                )
            elif "alcohol" in normalized or "alkohol" in normalized:
                constraints.append(
                    Constraint(
                        ConstraintKind.PROHIBITED_CATEGORY,
                        "exclude",
                        "alcohol",
                    )
                )
            elif "plastic" in normalized or "plastik" in normalized:
                constraints.append(
                    Constraint(ConstraintKind.MATERIAL, "exclude", "plastic")
                )
            elif "vegan" in normalized or "wegan" in normalized:
                constraints.append(
                    Constraint(ConstraintKind.CUSTOM, "require", "vegan")
                )
            elif "vegetarian" in normalized or "wegetarian" in normalized:
                constraints.append(
                    Constraint(ConstraintKind.CUSTOM, "require", "vegetarian")
                )
            elif any(
                phrase in normalized
                for phrase in ("budget", "deadline", "deliver before", "allergen")
            ):
                # These are policy principles already enforced by the concrete
                # budget/deadline/allergen rules above.
                continue
            else:
                raise WorkflowConflictError(
                    f"Unsupported default hard constraint: {raw_default}"
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
                   p.category, p.allergens_json, p.tags_json, p.stock,
                   p.merchant_id, p.currency AS product_currency
            FROM basket_items bi
            JOIN products p ON p.id = bi.product_id
            WHERE bi.basket_id = ?
            """,
            (basket_id,),
        ).fetchall()
        allowed_categories = {
            str(category).casefold()
            for category in load_json(contract_row["allowed_categories_json"], [])
        }
        forbidden_categories = {
            str(category).casefold()
            for category in load_json(contract_row["forbidden_categories_json"], [])
        }
        for row in item_rows:
            category = row["category"].casefold()
            if allowed_categories and category not in allowed_categories:
                raise WorkflowConflictError(
                    f"Product {row['product_id']} is outside the allowed categories"
                )
            if category in forbidden_categories:
                raise WorkflowConflictError(
                    f"Product {row['product_id']} is in a forbidden category"
                )
            if row["merchant_id"] != basket["merchant_id"]:
                raise WorkflowConflictError(
                    f"Product {row['product_id']} belongs to another merchant"
                )
            if row["product_currency"] != basket["currency"]:
                raise WorkflowConflictError(
                    f"Product {row['product_id']} uses another currency"
                )
        snapshot = BasketSnapshot(
            lines=tuple(
                BasketLine(
                    product_id=row["product_id"],
                    category=row["category"],
                    quantity=row["quantity"],
                    unit_price=Money(row["unit_price_cents"], basket["currency"]),
                    allergens=frozenset(load_json(row["allergens_json"], [])),
                    tags=frozenset(load_json(row["tags_json"], [])),
                    available_quantity=int(row["stock"]),
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
        self._record_guardrail_attestation(
            connection,
            mission_id,
            checks=[
                "contract_complete",
                "currency_match",
                "budget_all_in",
                "delivery_deadline",
                "explicit_allergens",
                "prohibited_categories",
                "material_constraints",
                "dietary_constraints",
                "allowed_categories",
                "forbidden_categories",
                "merchant_consistency",
                "inventory_availability",
                "user_default_constraints",
            ],
        )

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

    def _create_action_request(
        self,
        connection: sqlite3.Connection,
        mission_id: str,
        *,
        action_type: str,
        reason_code: str,
        question: str,
        options: list[dict[str, str]] | None = None,
        context: dict[str, Any] | None = None,
        owner: str = "user",
        expires_at: str | None = None,
    ) -> str:
        """Persist one resumable human-in-the-loop request.

        An equivalent pending request is reused so retries cannot fan out into
        duplicate notifications or conflicting decisions.
        """

        now = utc_now()
        connection.execute(
            """
            UPDATE action_requests
            SET status = 'expired', resolved_at = ?
            WHERE mission_id = ? AND action_type = ? AND reason_code = ?
              AND status = 'pending' AND expires_at IS NOT NULL AND expires_at <= ?
            """,
            (now, mission_id, action_type, reason_code, now),
        )
        existing = connection.execute(
            """
            SELECT id FROM action_requests
            WHERE mission_id = ? AND action_type = ? AND reason_code = ?
              AND status = 'pending'
              AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY created_at DESC LIMIT 1
            """,
            (mission_id, action_type, reason_code, now),
        ).fetchone()
        if existing is not None:
            return str(existing["id"])
        action_id = new_id("act")
        connection.execute(
            """
            INSERT INTO action_requests
                (id, mission_id, action_type, reason_code, question,
                 options_json, context_json, status, owner, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                action_id,
                mission_id,
                action_type,
                reason_code,
                question,
                dump_json(options or []),
                dump_json(context or {}),
                owner,
                expires_at,
                now,
            ),
        )
        return action_id

    def _refresh_expired_action(
        self,
        connection: sqlite3.Connection,
        action: sqlite3.Row,
    ) -> str:
        """Persist expiry and present a new, equivalent durable decision."""

        now = utc_now()
        connection.execute(
            """
            UPDATE action_requests
            SET status = 'expired', resolved_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (now, action["id"]),
        )
        refreshed_expiry = (
            (datetime.now(UTC) + timedelta(days=7)).isoformat(timespec="seconds")
            if action["expires_at"] is not None
            else None
        )
        refreshed_id = self._create_action_request(
            connection,
            action["mission_id"],
            action_type=action["action_type"],
            reason_code=action["reason_code"],
            question=action["question"],
            options=load_json(action["options_json"], []),
            context=load_json(action["context_json"], {}),
            owner=action["owner"],
            expires_at=refreshed_expiry,
        )
        self._event(
            connection,
            action["mission_id"],
            "action.refreshed_after_expiry",
            "system",
            "Action request refreshed",
            "The expired decision was recorded and a fresh request was created.",
            severity="action",
            payload={"old_action_request_id": action["id"], "action_request_id": refreshed_id},
        )
        return refreshed_id

    @staticmethod
    def _resolve_action_requests(
        connection: sqlite3.Connection,
        mission_id: str,
        *,
        resolution: dict[str, Any],
        action_type: str | None = None,
    ) -> None:
        conditions = ["mission_id = ?", "status = 'pending'"]
        parameters: list[Any] = [mission_id]
        if action_type is not None:
            conditions.append("action_type = ?")
            parameters.append(action_type)
        connection.execute(
            f"""
            UPDATE action_requests
            SET status = 'resolved', resolved_at = ?, resolution_json = ?
            WHERE {' AND '.join(conditions)}
            """,
            (utc_now(), dump_json(resolution), *parameters),
        )

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
        self._bind_approval_evidence(connection, approval_id, mission_id)
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
        approval_evidence = (
            connection.execute(
                "SELECT * FROM approval_evidence WHERE approval_id = ?",
                (approval["id"],),
            ).fetchone()
            if approval is not None
            else None
        )
        event_rows = connection.execute(
            "SELECT * FROM mission_events WHERE mission_id = ? ORDER BY id ASC",
            (mission_id,),
        ).fetchall()
        delivery_rows = connection.execute(
            """
            SELECT d.*, m.name AS merchant_name, mission.currency AS currency
            FROM delivery_options d
            JOIN merchants m ON m.id = d.merchant_id
            JOIN missions mission ON mission.id = d.mission_id
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
        action_rows = connection.execute(
            """
            SELECT * FROM action_requests
            WHERE mission_id = ?
            ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, created_at DESC
            """,
            (mission_id,),
        ).fetchall()
        draft = connection.execute(
            "SELECT * FROM mission_drafts WHERE mission_id = ?", (mission_id,)
        ).fetchone()
        card_request = connection.execute(
            """
            SELECT * FROM virtual_card_requests
            WHERE mission_id = ? ORDER BY created_at DESC LIMIT 1
            """,
            (mission_id,),
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
                # Incomplete drafts use an internal sentinel because the legacy
                # SQLite column is non-nullable. Never expose that sentinel as a
                # user-confirmed deadline through the HTTP contract.
                "deadline": mission["deadline"] if contract is not None else None,
                "risk_level": mission["risk_level"],
                "requires_approval": bool(mission["requires_approval"]),
                "locale": mission["locale"],
                "timezone": mission["timezone"],
                "revision": mission["revision"],
            },
            "contract": self._contract_projection(contract) if contract else None,
            "basket": basket_projection,
            "approval": (
                self._approval_projection(approval, approval_evidence)
                if approval
                else None
            ),
            "approvals": (
                [self._approval_projection(approval, approval_evidence)]
                if approval
                else []
            ),
            "events": [self._event_projection(row) for row in event_rows],
            "metrics": metrics,
            "delivery_options": [self._delivery_projection(row) for row in delivery_rows],
            "payment_attempts": [self._payment_projection(row) for row in payments],
            "order": self._order_projection(order) if order else None,
            "draft": load_json(draft["draft_json"], None) if draft else None,
            "action_requests": [self._action_projection(row) for row in action_rows],
            "funding": (
                {
                    "status": card_request["status"],
                    "plan_hash": card_request["plan_hash"],
                    "merchant_lock": card_request["merchant_lock"],
                    "max_amount": money(card_request["max_amount_cents"]),
                    "currency": card_request["currency"],
                    "restrictions": load_json(card_request["restrictions_json"], {}),
                    "expires_at": card_request["expires_at"],
                    "contains_card_secrets": False,
                }
                if card_request is not None
                else {
                    "status": "not_ready",
                    "contains_card_secrets": False,
                }
            ),
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
            "title": self._title_from_transcript(mission["raw_voice_transcript"]),
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
    def _approval_projection(
        approval: sqlite3.Row,
        evidence: sqlite3.Row | None = None,
    ) -> dict[str, Any]:
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
            "plan_hash": evidence["plan_hash"] if evidence is not None else None,
            "merchant_id": evidence["merchant_id"] if evidence is not None else None,
            "amount": money(evidence["amount_cents"]) if evidence is not None else None,
            "currency": evidence["currency"] if evidence is not None else None,
        }

    @staticmethod
    def _action_projection(action: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": action["id"],
            "mission_id": action["mission_id"],
            "type": action["action_type"],
            "reason_code": action["reason_code"],
            "question": action["question"],
            "options": load_json(action["options_json"], []),
            "context": load_json(action["context_json"], {}),
            "status": action["status"],
            "owner": action["owner"],
            "expires_at": action["expires_at"],
            "created_at": action["created_at"],
            "resolved_at": action["resolved_at"],
            "resolution": load_json(action["resolution_json"], None),
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
            "currency": delivery["currency"],
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
    def _title_from_transcript(transcript: str, max_length: int = 72) -> str:
        normalized = " ".join(transcript.split()).strip()
        first_sentence = re.split(r"(?<=[.!?])\s+", normalized, maxsplit=1)[0]
        candidate = first_sentence.rstrip(".!?").strip() or normalized
        if len(candidate) <= max_length:
            return candidate
        shortened = candidate[: max_length - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
        return f"{shortened or candidate[: max_length - 1]}…"

    @staticmethod
    def _interpret(transcript: str, locale: str, timezone: str) -> dict[str, Any]:
        try:
            zone = ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            zone = UTC
        draft = TranscriptInterpreter(clock=lambda: datetime.now(zone)).interpret(transcript)
        projection = MissionWorkflow._draft_projection(draft)
        budget = draft.budget
        deadline = draft.deadline
        participants = draft.participants
        title = MissionWorkflow._title_from_transcript(draft.transcript)
        if draft.shopping_scope == ShoppingScope.GIFTS:
            goal = "buy_gifts"
            mission_type = "gift_shopping"
            allowed_categories = ["gifts", "toys", "books", "games", "creative"]
        elif draft.shopping_scope == ShoppingScope.PARTY_SUPPLIES:
            goal = "prepare_birthday_party"
            mission_type = "party_shopping"
            allowed_categories = [
                "snacks",
                "drinks",
                "cake",
                "decorations",
                "tableware",
                "candles",
                "napkins",
                "party bags",
            ]
        else:
            goal = "clarify_shopping_mission"
            mission_type = "shopping"
            allowed_categories = []

        hard_constraints: list[dict[str, Any]] = []
        if budget is not None:
            hard_constraints.append(
                {
                    "type": "budget",
                    "operator": "less_than_or_equal",
                    "value": money(budget.minor),
                    "currency": budget.currency,
                }
            )
        if deadline is not None:
            hard_constraints.append(
                {
                    "type": "delivery_deadline",
                    "operator": "before_or_at",
                    "value": deadline.isoformat(),
                }
            )
        hard_constraints.extend(
            {
                "type": constraint.kind.value,
                "operator": constraint.operator,
                "value": constraint.value,
            }
            for constraint in draft.constraints
        )
        facts = [
            f"{participants} people" if participants is not None else None,
            (
                f"up to {money(budget.minor):.2f} {budget.currency}"
                if budget is not None
                else None
            ),
            f"by {deadline.strftime('%Y-%m-%d %H:%M')}" if deadline is not None else None,
        ]
        subtitle = " · ".join(item for item in facts if item) or "Needs clarification"
        questions = MissionWorkflow._clarification_questions(draft)
        return {
            "title": title,
            "subtitle": subtitle,
            "goal": goal,
            "mission_type": mission_type,
            "shopping_scope": draft.shopping_scope.value,
            "recipient_age": draft.recipient_age,
            "participants": participants,
            "budget_limit_cents": budget.minor if budget is not None else None,
            "currency": budget.currency if budget is not None else "PLN",
            "deadline": deadline.isoformat() if deadline is not None else None,
            "hard_constraints": hard_constraints,
            "allowed_categories": allowed_categories,
            # Category exclusions are guardrails only when the user said them
            # or saved them in their profile; age and occasion are not consent
            # to invent additional purchase constraints.
            "forbidden_categories": [],
            "confidence": 1.0 if draft.ready_for_planning else 0.5,
            "ready_for_planning": draft.ready_for_planning,
            "missing_information": list(draft.missing_fields),
            "ambiguities": list(draft.ambiguities),
            "clarification_questions": questions,
            "draft": projection,
            "confirmation": (
                f"I understood: {subtitle}."
                if draft.ready_for_planning
                else questions[0]
            ),
        }

    @staticmethod
    def _draft_projection(draft: MissionDraft) -> dict[str, Any]:
        def evidence_value(value: Any) -> Any:
            if isinstance(value, Money):
                return {"minor": value.minor, "currency": value.currency}
            if isinstance(value, Decimal):
                return format(value, "f")
            if isinstance(value, Constraint):
                return {
                    "type": value.kind.value,
                    "operator": value.operator,
                    "value": value.value,
                }
            if hasattr(value, "isoformat"):
                return value.isoformat()
            if hasattr(value, "value"):
                return value.value
            return value

        return {
            "transcript": draft.transcript,
            "occasion": draft.occasion.value,
            "shopping_scope": draft.shopping_scope.value,
            "recipient_age": draft.recipient_age,
            "participants": draft.participants,
            "budget": (
                {"minor": draft.budget.minor, "currency": draft.budget.currency}
                if draft.budget is not None
                else None
            ),
            "deadline_date": (
                draft.deadline_date.isoformat() if draft.deadline_date is not None else None
            ),
            "deadline_time": (
                draft.deadline_time.isoformat() if draft.deadline_time is not None else None
            ),
            "deadline": draft.deadline.isoformat() if draft.deadline is not None else None,
            "constraints": [
                {
                    "type": item.kind.value,
                    "operator": item.operator,
                    "value": item.value,
                }
                for item in draft.constraints
            ],
            "evidence": [
                {
                    "field": item.field,
                    "value": evidence_value(item.value),
                    "source_text": item.source_text,
                    "start": item.start,
                    "end": item.end,
                    "rule": item.rule,
                    "confidence": item.confidence,
                }
                for item in draft.evidence
            ],
            "missing_fields": list(draft.missing_fields),
            "ambiguities": list(draft.ambiguities),
            "ready_for_planning": draft.ready_for_planning,
        }

    @staticmethod
    def _clarification_questions(draft: MissionDraft) -> list[str]:
        questions: list[str] = []
        for field in draft.missing_fields:
            if field == "shopping_scope":
                questions.append(
                    "Czy kupuję prezenty, czy wyposażenie przyjęcia urodzinowego?"
                    if draft.occasion == Occasion.BIRTHDAY
                    else "Jakie wymagania powinien spełniać ten zakup?"
                )
            elif field == "participants":
                if draft.shopping_scope != ShoppingScope.AMBIGUOUS:
                    questions.append("Dla ilu osób mam zrobić zakupy?")
            elif field == "recipient_age":
                questions.append("W jakim wieku są osoby, dla których kupuję prezenty?")
            elif field in {"budget", "budget_currency"}:
                questions.append("Jaki jest maksymalny budżet i waluta?")
            elif field == "deadline":
                questions.append("Na jaki dzień i godzinę potrzebna jest dostawa?")
            elif field == "deadline_time":
                questions.append("Do której godziny tego dnia potrzebna jest dostawa?")
        return questions or ["Czy potwierdzasz ten kontrakt misji?"]

    @staticmethod
    def _catalog_constraints(
        interpreted: dict[str, Any],
        policy: MissionExecutionPolicy,
    ) -> tuple[Constraint, ...]:
        """Translate only explicit transcript and saved-profile constraints.

        Budget and deadline are represented by dedicated search fields.  They
        are deliberately excluded from offer-level checks, while absent
        product constraints are never inferred from the occasion or age.
        """

        constraints: list[Constraint] = []
        draft = interpreted.get("draft", {})
        for item in draft.get("constraints", []):
            try:
                kind = ConstraintKind(str(item["type"]))
            except (KeyError, ValueError):
                kind = ConstraintKind.CUSTOM
            constraints.append(
                Constraint(
                    kind,
                    str(item.get("operator", "require")),
                    item.get("value", f"unknown:{item.get('type', 'constraint')}"),
                )
            )

        for raw_default in policy.default_constraints:
            normalized = str(raw_default).casefold()
            if "nut" in normalized or "orzech" in normalized:
                constraint = Constraint(ConstraintKind.ALLERGEN, "exclude", "nuts")
            elif "alcohol" in normalized or "alkohol" in normalized:
                constraint = Constraint(
                    ConstraintKind.PROHIBITED_CATEGORY,
                    "exclude",
                    "alcohol",
                )
            elif "plastic" in normalized or "plastik" in normalized:
                constraint = Constraint(ConstraintKind.MATERIAL, "exclude", "plastic")
            elif "vegan" in normalized or "wegan" in normalized:
                constraint = Constraint(ConstraintKind.CUSTOM, "require", "vegan")
            elif "vegetarian" in normalized or "wegetarian" in normalized:
                constraint = Constraint(
                    ConstraintKind.CUSTOM,
                    "require",
                    "vegetarian",
                )
            elif any(
                phrase in normalized
                for phrase in ("budget", "deadline", "deliver before", "allergen")
            ):
                # These general principles are enforced by the concrete budget,
                # deadline and explicit allergen contract fields.
                continue
            else:
                # An unprovable profile rule must stop catalog selection rather
                # than being silently dropped.
                constraint = Constraint(
                    ConstraintKind.CUSTOM,
                    "require",
                    f"unsupported-profile-default:{raw_default}",
                )
            if constraint not in constraints:
                constraints.append(constraint)
        return tuple(constraints)

    @staticmethod
    def _load_catalog_offers(
        connection: sqlite3.Connection,
    ) -> tuple[ProductOffer, ...]:
        rows = connection.execute(
            """
            SELECT p.*, m.reliability_score
            FROM products p
            JOIN merchants m ON m.id = p.merchant_id
            WHERE m.active = 1
            ORDER BY p.merchant_id, p.id
            """
        ).fetchall()
        return tuple(
            ProductOffer(
                product_id=row["id"],
                merchant_id=row["merchant_id"],
                merchant_reliability=float(row["reliability_score"]),
                category=row["category"],
                price=Money(int(row["price_cents"]), row["currency"]),
                stock=int(row["stock"]),
                allergens=frozenset(load_json(row["allergens_json"], [])),
                tags=frozenset(load_json(row["tags_json"], [])),
                rating=float(row["rating"]),
                substitute_group=row["substitute_group"],
            )
            for row in rows
        )

    @staticmethod
    def _catalog_plan_products(
        connection: sqlite3.Connection,
        plan: CatalogPlan,
    ) -> dict[str, sqlite3.Row]:
        product_ids = tuple(line.product_id for line in plan.lines)
        if not product_ids:
            raise WorkflowConflictError("Catalog planner returned an empty basket")
        placeholders = ",".join("?" for _ in product_ids)
        rows = connection.execute(
            f"SELECT * FROM products WHERE id IN ({placeholders})",
            product_ids,
        ).fetchall()
        products = {row["id"]: row for row in rows}
        if set(products) != set(product_ids):
            raise WorkflowConflictError("Catalog plan references an unavailable product")
        if any(row["merchant_id"] != plan.merchant_id for row in rows):
            raise WorkflowConflictError("Catalog plan mixes merchant inventories")
        if any(row["currency"] != plan.subtotal.currency for row in rows):
            raise WorkflowConflictError("Catalog plan mixes currencies")
        return products

    @staticmethod
    def _substitutable_basket_product(
        connection: sqlite3.Connection,
        basket_id: str,
    ) -> str | None:
        """Pick an actual planned line that has an in-stock same-merchant substitute."""

        row = connection.execute(
            """
            SELECT bi.product_id
            FROM basket_items bi
            JOIN products p ON p.id = bi.product_id
            WHERE bi.basket_id = ?
              AND p.substitute_group IS NOT NULL
              AND EXISTS (
                  SELECT 1
                  FROM products replacement
                  WHERE replacement.id != p.id
                    AND replacement.merchant_id = p.merchant_id
                    AND replacement.substitute_group = p.substitute_group
                    AND replacement.category = p.category
                    AND replacement.currency = p.currency
                    AND replacement.allergens_json = p.allergens_json
                    AND replacement.stock >= bi.quantity
              )
            ORDER BY bi.product_id
            LIMIT 1
            """,
            (basket_id,),
        ).fetchone()
        return str(row["product_id"]) if row is not None else None

    @staticmethod
    def _first_basket_product(
        connection: sqlite3.Connection,
        basket_id: str,
    ) -> str | None:
        row = connection.execute(
            """
            SELECT product_id FROM basket_items
            WHERE basket_id = ?
            ORDER BY product_id
            LIMIT 1
            """,
            (basket_id,),
        ).fetchone()
        return str(row["product_id"]) if row is not None else None

    @staticmethod
    def _delivery_time(deadline: str, hours_before: int) -> str:
        return (datetime.fromisoformat(deadline) - timedelta(hours=hours_before)).isoformat()
