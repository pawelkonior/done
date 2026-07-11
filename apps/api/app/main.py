"""FastAPI composition root for the Done modular monolith."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict
from hashlib import sha256
import os
import re
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.datastructures import UploadFile as StarletteUploadFile

from .access import ApiAccessSettings
from .application.mission_service import (
    EmptyTranscriptionError,
    MissionApplicationService,
    MissionServiceSettings,
    SpeechInputUnavailableError,
)
from .application.portfolio_planning_service import PortfolioPlanningService
from .application.ports.ai import SpeechToTextPort
from .application.ports.realtime import RealtimeSessionPort
from .application.user_service import UserApplicationService
from .config import (
    PortfolioShadowSettings,
    RealtimeSettings,
    get_portfolio_shadow_settings,
    get_realtime_settings,
    get_transcription_settings,
)
from .database import PRODUCTS, Database
from .infrastructure.ai.openai_realtime import (
    OpenAIRealtimeAdapter,
    RealtimeUnavailableError,
)
from .infrastructure.ai.openai_transcription import (
    OpenAITranscriptionAdapter,
    OpenAITranscriptionError,
)
from .infrastructure.persistence.user_repository import SQLiteUserRepository
from .presentation.user_router import create_user_router
from .schemas import (
    ActionResolveRequest,
    ApprovalResolveRequest,
    DeliveryOptionSelectionRequest,
    FailureInjectionRequest,
    HumanSupportRequest,
    MissionCorrectionRequest,
    MissionCancelRequest,
    MissionCreateRequest,
    RealtimeClientSecretRequest,
    ReplanMissionRequest,
)
from .workflow import (
    ApprovalNotFoundError,
    MissionNotFoundError,
    MissionWorkflow,
    WorkflowConflictError,
)


def _parse_if_match(value: str | None) -> int | None:
    if value is None or value.strip() == "*":
        return None
    match = re.fullmatch(r'(?:W/)?"?(\d+)"?', value.strip())
    if match is None or int(match.group(1)) < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="If-Match must contain a positive mission revision",
        )
    return int(match.group(1))


def _expected_revision(body_revision: int | None, if_match: str | None) -> int | None:
    header_revision = _parse_if_match(if_match)
    if (
        body_revision is not None
        and header_revision is not None
        and body_revision != header_revision
    ):
        raise WorkflowConflictError(
            "expected_revision in the body does not match the If-Match header"
        )
    return header_revision if header_revision is not None else body_revision


def _required_revision(body_revision: int | None, if_match: str | None = None) -> int:
    revision = _expected_revision(body_revision, if_match)
    if revision is None:
        raise WorkflowConflictError(
            "This mutation requires the exact current mission revision"
        )
    return revision


def _completed_bound(value: str | None, *, end_of_day: bool) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized):
        try:
            parsed_date = date.fromisoformat(normalized)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="completed_from and completed_to must be ISO dates or datetimes",
            ) from exc
        parsed_datetime = datetime.combine(
            parsed_date,
            time.max if end_of_day else time.min,
            tzinfo=UTC,
        )
        return parsed_datetime.isoformat(timespec="milliseconds")
    try:
        parsed_datetime = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed_date = date.fromisoformat(normalized)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="completed_from and completed_to must be ISO dates or datetimes",
            ) from exc
        parsed_datetime = datetime.combine(
            parsed_date,
            time.max if end_of_day else time.min,
            tzinfo=UTC,
        )
    if parsed_datetime.tzinfo is None:
        parsed_datetime = parsed_datetime.replace(tzinfo=UTC)
    return parsed_datetime.astimezone(UTC).isoformat(timespec="milliseconds")


def create_app(
    database_path: str | Path | None = None,
    *,
    mission_settings: MissionServiceSettings | None = None,
    speech_to_text: SpeechToTextPort | None = None,
    realtime: RealtimeSessionPort | None = None,
    realtime_settings: RealtimeSettings | None = None,
    portfolio_shadow_settings: PortfolioShadowSettings | None = None,
) -> FastAPI:
    resolved_path = database_path or os.getenv(
        "DONE_DB_PATH", str(Path(__file__).resolve().parents[1] / "done.sqlite3")
    )
    commerce_mode = os.getenv("DONE_COMMERCE_MODE", "demo").strip().casefold()
    access_settings = ApiAccessSettings.from_env(commerce_mode=commerce_mode)
    database = Database(resolved_path)
    database.initialize()
    portfolio_planner = PortfolioPlanningService()
    resolved_shadow_settings = portfolio_shadow_settings or get_portfolio_shadow_settings()
    workflow = MissionWorkflow(
        database,
        portfolio_planner=portfolio_planner,
        portfolio_shadow_settings=resolved_shadow_settings,
        commerce_mode=commerce_mode,
    )
    user_service = UserApplicationService(SQLiteUserRepository(database))
    runtime_settings = mission_settings or MissionServiceSettings.from_env()
    transcription_settings = get_transcription_settings()
    live_settings = realtime_settings or get_realtime_settings()
    resolved_speech = speech_to_text
    if runtime_settings.stt_enabled and resolved_speech is None:
        resolved_speech = OpenAITranscriptionAdapter(transcription_settings)
    resolved_realtime = realtime
    if live_settings.enabled and resolved_realtime is None:
        resolved_realtime = OpenAIRealtimeAdapter(live_settings)
    mission_service = MissionApplicationService(
        workflow,
        speech_to_text=resolved_speech,
        user_service=user_service,
        settings=runtime_settings,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):  # type: ignore[no-untyped-def]
        yield
        await mission_service.aclose()
        if resolved_realtime is not None:
            await resolved_realtime.aclose()

    application = FastAPI(
        title="Done API",
        version="1.0.0",
        description=(
            "Voice-driven, self-healing commerce missions with deterministic safety rules "
            "and server-side OpenAI speech services."
        ),
        lifespan=lifespan,
    )
    application.state.database = database
    application.state.workflow = workflow
    application.state.portfolio_planner = portfolio_planner
    application.state.portfolio_shadow_settings = resolved_shadow_settings
    application.state.user_service = user_service
    application.state.mission_service = mission_service
    application.state.realtime = resolved_realtime
    application.state.access_settings = access_settings
    allowed_origins = [
        item.strip()
        for item in os.getenv(
            "DONE_CORS_ORIGINS",
            "http://localhost:8081,http://127.0.0.1:8081",
        ).split(",")
        if item.strip()
    ]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Authorization",
            "Content-Type",
            "If-Match",
            "X-Request-ID",
        ],
        expose_headers=["ETag", "X-Request-ID"],
    )
    application.include_router(create_user_router(user_service))

    @application.middleware("http")
    async def protect_and_disable_api_caching(  # type: ignore[no-untyped-def]
        request: Request, call_next
    ):
        request_id = request.headers.get("X-Request-ID") or uuid4().hex
        protected = request.url.path.startswith("/v1/") and request.url.path not in {
            "/v1/health",
        }
        if (
            protected
            and request.method != "OPTIONS"
            and not access_settings.accepts(request.headers.get("Authorization"))
        ):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "error": "authentication_required",
                    "message": "A valid bearer token is required",
                },
                headers={
                    "Cache-Control": "no-store",
                    "WWW-Authenticate": "Bearer",
                    "X-Request-ID": request_id[:128],
                },
            )
        response = await call_next(request)
        if request.url.path.startswith("/v1/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-ID"] = request_id[:128]
        return response

    @application.exception_handler(MissionNotFoundError)
    async def mission_not_found(_: Request, exc: MissionNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "mission_not_found", "message": f"Mission {exc} was not found."},
        )

    @application.exception_handler(ApprovalNotFoundError)
    async def approval_not_found(_: Request, exc: ApprovalNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": "approval_not_found",
                "message": f"Approval {exc} was not found.",
            },
        )

    @application.exception_handler(WorkflowConflictError)
    async def workflow_conflict(_: Request, exc: WorkflowConflictError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"error": "workflow_conflict", "message": str(exc)},
        )

    @application.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {
                "location": ".".join(str(part) for part in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": "validation_error",
                "message": "Request validation failed",
                "fields": fields,
            },
        )

    @application.exception_handler(SpeechInputUnavailableError)
    async def speech_unavailable(
        _: Request, exc: SpeechInputUnavailableError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "speech_unavailable", "message": str(exc)},
        )

    @application.exception_handler(EmptyTranscriptionError)
    async def empty_transcription(
        _: Request, exc: EmptyTranscriptionError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"error": "empty_transcription", "message": str(exc)},
        )

    @application.exception_handler(OpenAITranscriptionError)
    async def transcription_failed(
        _: Request, exc: OpenAITranscriptionError
    ) -> JSONResponse:
        message = str(exc)
        return JSONResponse(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_CONTENT
                if exc.client_error
                else status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            content={"error": "transcription_failed", "message": message},
        )

    @application.exception_handler(RealtimeUnavailableError)
    async def realtime_unavailable(
        _: Request, exc: RealtimeUnavailableError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "realtime_unavailable", "message": str(exc)},
        )

    @application.get("/health", tags=["system"])
    @application.get("/v1/health", tags=["system"], include_in_schema=False)
    def health() -> dict[str, object]:
        with database.reader() as connection:
            connection.execute("SELECT 1").fetchone()
            product_count = connection.execute(
                "SELECT COUNT(*) AS count FROM products"
            ).fetchone()["count"]
        return {
            "status": "ok",
            "service": "done-api",
            "version": "1.0.0",
            "database": "ok",
            "seeded_products": product_count,
        }

    @application.get("/v1/runtime/capabilities", tags=["system"])
    async def runtime_capabilities() -> dict[str, Any]:
        capabilities = await mission_service.capabilities()
        if resolved_realtime is None:
            capabilities["realtime"] = {
                "status": "disabled",
                "provider": "openai",
                "model": live_settings.model,
                "detail": "Set DONE_REALTIME_ENABLED=true to enable live voice.",
            }
        else:
            try:
                capabilities["realtime"] = asdict(await resolved_realtime.health())
            except Exception:
                capabilities["realtime"] = {
                    "status": "unavailable",
                    "provider": "openai",
                    "model": live_settings.model,
                    "detail": "Live voice health check failed.",
                }
        capabilities["portfolio_automation"] = {
            "shadow_mode": resolved_shadow_settings.enabled,
            "autonomy_enabled": resolved_shadow_settings.autonomy_enabled,
            "automatic_purchases_default": False,
            "promotion_gate": resolved_shadow_settings.promotion_gate,
        }
        return capabilities

    @application.post(
        "/v1/realtime/client-secret",
        tags=["realtime"],
        summary="Mint a short-lived OpenAI Realtime client secret",
    )
    async def realtime_client_secret(
        payload: RealtimeClientSecretRequest,
    ) -> dict[str, object]:
        if resolved_realtime is None or not live_settings.configured:
            raise RealtimeUnavailableError(
                "Live voice is not configured on this server"
            )
        safety_identifier = sha256(b"done:demo-user").hexdigest()
        mission_context: dict[str, Any] | None = None
        if payload.mission_id:
            detail = workflow.get_detail(payload.mission_id)
            pending_action = next(
                (
                    item
                    for item in detail.get("action_requests", [])
                    if item.get("status") == "pending"
                    and item.get("owner") == "user"
                ),
                None,
            )
            approval = detail.get("approval")
            pending_approval = (
                approval
                if isinstance(approval, dict) and approval.get("status") == "pending"
                else None
            )
            mission_context = {
                "mission": {
                    "id": detail["mission"]["id"],
                    "revision": detail["mission"]["revision"],
                    "status": detail["mission"]["status"],
                    "contract_available": detail.get("contract") is not None,
                },
                "approval": (
                    {
                        "id": pending_approval.get("id"),
                        "status": pending_approval.get("status"),
                        "plan_hash": pending_approval.get("plan_hash"),
                        "merchant_id": pending_approval.get("merchant_id"),
                        "amount": pending_approval.get("amount"),
                        "currency": pending_approval.get("currency"),
                        "choices": [
                            item.get("id")
                            for item in pending_approval.get("options", [])
                            if isinstance(item, dict)
                        ],
                    }
                    if pending_approval
                    else None
                ),
                "action": (
                    {
                        "id": pending_action.get("id"),
                        "status": pending_action.get("status"),
                        "owner": pending_action.get("owner"),
                        "choices": [
                            item.get("id")
                            for item in pending_action.get("options", [])
                            if isinstance(item, dict)
                        ],
                    }
                    if pending_action
                    else None
                ),
                # Titles and questions can contain user, catalog or merchant text.
                # They are display-only context and are never part of tool bindings.
                "untrusted_data": {
                    "mission_title": detail["mission"].get("title"),
                    "action_question": (
                        pending_action.get("question") if pending_action else None
                    ),
                },
            }
        secret = await resolved_realtime.create_client_secret(
            language=payload.language,
            safety_identifier=safety_identifier,
            mission_context=mission_context,
        )
        return {
            "value": secret.value,
            "expires_at": secret.expires_at,
            "model": secret.model,
            "voice": secret.voice,
        }

    @application.post(
        "/v1/missions/text",
        status_code=status.HTTP_201_CREATED,
        tags=["missions"],
    )
    async def create_text_mission(payload: MissionCreateRequest) -> dict[str, object]:
        return await mission_service.create_from_text(
            transcript=payload.transcript or "",
            locale=payload.locale,
            timezone=payload.timezone,
        )

    @application.post(
        "/v1/missions/voice",
        status_code=status.HTTP_201_CREATED,
        tags=["missions"],
        summary="Create a mission from audio (or a JSON transcript for compatibility)",
    )
    async def create_voice_mission(request: Request) -> dict[str, object]:
        content_type = request.headers.get("content-type", "").casefold()
        if content_type.startswith("multipart/form-data"):
            form = await request.form()
            upload = form.get("file")
            if not isinstance(upload, StarletteUploadFile):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="multipart field 'file' is required",
                )
            data = await upload.read(transcription_settings.max_upload_bytes + 1)
            if len(data) > transcription_settings.max_upload_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="audio exceeds the configured upload limit",
                )
            locale = str(form.get("locale") or "pl-PL")[:32]
            timezone = str(form.get("timezone") or "Europe/Warsaw")[:64]
            language = str(form.get("language") or locale).split("-", 1)[0]
            return await mission_service.create_from_audio(
                data=data,
                filename=upload.filename or "voice.m4a",
                content_type=upload.content_type or "application/octet-stream",
                language=language,
                locale=locale,
                timezone=timezone,
            )

        try:
            payload = MissionCreateRequest.model_validate(await request.json())
        except (ValidationError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A valid JSON transcript or multipart audio file is required",
            ) from exc
        return await mission_service.create_from_text(
            transcript=payload.transcript or "",
            locale=payload.locale,
            timezone=payload.timezone,
            input_mode="voice",
        )

    @application.get("/v1/missions", tags=["missions"])
    def list_missions(
        mission_status: Annotated[str | None, Query(alias="status")] = None,
        q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
        completed_from: Annotated[str | None, Query(max_length=64)] = None,
        completed_to: Annotated[str | None, Query(max_length=64)] = None,
        sort: Annotated[
            Literal["newest", "oldest", "updated", "deadline"], Query()
        ] = "newest",
        requires_action: Annotated[bool | None, Query()] = None,
    ) -> dict[str, object]:
        normalized_from = _completed_bound(completed_from, end_of_day=False)
        normalized_to = _completed_bound(completed_to, end_of_day=True)
        if normalized_from and normalized_to and normalized_from > normalized_to:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="completed_from cannot be after completed_to",
            )
        missions = workflow.list_missions(
            mission_status,
            query_text=q,
            completed_from=normalized_from,
            completed_to=normalized_to,
            sort=sort,
            requires_action=requires_action,
        )
        return {"missions": missions, "items": missions, "total": len(missions)}

    @application.get("/v1/missions/{mission_id}", tags=["missions"])
    def mission_detail(mission_id: str) -> dict[str, object]:
        return workflow.get_detail(mission_id)

    @application.get("/v1/missions/{mission_id}/portfolio-decisions", tags=["missions"])
    def portfolio_decisions(mission_id: str) -> dict[str, object]:
        return workflow.get_portfolio_decisions(mission_id)

    @application.post("/v1/missions/{mission_id}/portfolio-shadow", tags=["missions"])
    def run_portfolio_shadow(mission_id: str) -> dict[str, object]:
        if not resolved_shadow_settings.enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Portfolio shadow mode is disabled",
            )
        return workflow.run_portfolio_shadow(mission_id)

    @application.get(
        "/v1/missions/{mission_id}/portfolio-shadow-audits", tags=["missions"]
    )
    def portfolio_shadow_audits(mission_id: str) -> dict[str, object]:
        return workflow.get_portfolio_shadow_audits(mission_id)

    @application.get("/v1/portfolio/shadow/telemetry", tags=["system"])
    def portfolio_shadow_telemetry() -> dict[str, object]:
        return {
            "enabled": resolved_shadow_settings.enabled,
            "autonomy_enabled": resolved_shadow_settings.autonomy_enabled,
            "promotion_gate": resolved_shadow_settings.promotion_gate,
            "metrics": workflow.get_portfolio_shadow_telemetry(),
        }

    @application.post("/v1/missions/{mission_id}/replan", tags=["missions"])
    def replan_mission(
        mission_id: str,
        payload: ReplanMissionRequest,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        return workflow.replan_mission(
            mission_id,
            expected_revision=_expected_revision(payload.expected_revision, if_match),
        )

    @application.put(
        "/v1/missions/{mission_id}/delivery-option",
        tags=["missions"],
    )
    def select_delivery_option(
        mission_id: str,
        payload: DeliveryOptionSelectionRequest,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        return workflow.select_delivery_option(
            mission_id=mission_id,
            delivery_option_id=payload.delivery_option_id,
            expected_revision=_required_revision(payload.expected_revision, if_match),
        )

    @application.post(
        "/v1/missions/{mission_id}/corrections",
        tags=["missions"],
    )
    def correct_mission(
        mission_id: str,
        payload: MissionCorrectionRequest,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        return workflow.apply_correction(
            mission_id=mission_id,
            correction=payload.correction,
            expected_revision=_required_revision(payload.expected_revision, if_match),
        )

    @application.get("/v1/missions/{mission_id}/events", tags=["missions"])
    def mission_events(
        mission_id: str,
        after_id: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, object]:
        return workflow.get_events(mission_id, after_id)

    @application.post("/v1/missions/{mission_id}/cancel", tags=["missions"])
    def cancel_mission(
        mission_id: str,
        payload: MissionCancelRequest | None = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        return workflow.cancel_mission(
            mission_id,
            expected_revision=_required_revision(
                payload.expected_revision if payload is not None else None,
                if_match,
            ),
        )

    @application.post("/v1/approvals/{approval_id}/resolve", tags=["approvals"])
    def resolve_approval(
        approval_id: str, payload: ApprovalResolveRequest
    ) -> dict[str, object]:
        return workflow.resolve_approval(
            approval_id=approval_id,
            choice=payload.choice,
            voice_transcript=payload.voice_transcript,
            expected_revision=_required_revision(payload.expected_revision),
            expected_amount=payload.amount,
            expected_currency=payload.currency,
            expected_plan_hash=payload.plan_hash,
            expected_merchant_id=payload.merchant_id,
        )

    @application.post(
        "/v1/action-requests/{action_request_id}/resolve",
        tags=["actions"],
    )
    def resolve_action_request(
        action_request_id: str,
        payload: ActionResolveRequest,
    ) -> dict[str, object]:
        return workflow.resolve_action_request(
            action_request_id,
            payload.choice,
            voice_transcript=payload.voice_transcript,
            expected_revision=_required_revision(payload.expected_revision),
        )

    @application.post("/v1/missions/{mission_id}/support", tags=["actions"])
    def request_human_support(
        mission_id: str,
        payload: HumanSupportRequest,
    ) -> dict[str, object]:
        return workflow.request_human_support(
            mission_id,
            reason=payload.reason,
            expected_revision=_required_revision(payload.expected_revision),
        )

    @application.post(
        "/v1/demo/failures",
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    def inject_failure(payload: FailureInjectionRequest) -> dict[str, object]:
        if not runtime_settings.demo_endpoints_enabled:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return workflow.inject_failure(payload.mission_id, payload.failure_type)

    @application.post("/v1/demo/reset", tags=["demo"])
    def reset_demo() -> dict[str, object]:
        if not runtime_settings.demo_endpoints_enabled:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        with database.reader() as connection:
            deleted_count = connection.execute(
                "SELECT COUNT(*) AS count FROM missions"
            ).fetchone()["count"]
        database.reset()
        return {
            "status": "reset",
            "missions_deleted": deleted_count,
            "seeded_products": len(PRODUCTS),
        }

    return application


app = create_app()
