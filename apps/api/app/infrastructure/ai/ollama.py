"""Resilient async adapter for the native Ollama API."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import datetime
import re
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from app.application.ports.ai import (
    AIChatResponse,
    AIHealth,
    AIMessage,
    AIResult,
    AITool,
    AIToolCall,
    MissionIntentDraft,
)
from app.config import AISettings, get_ai_settings


ResultT = TypeVar("ResultT", bound=BaseModel)


class OllamaProtocolError(RuntimeError):
    """Ollama returned a syntactically valid but unusable response."""


_NUMBER_WORDS = {
    "jednego": 1,
    "dwojga": 2,
    "trojga": 3,
    "czworga": 4,
    "pięciorga": 5,
    "sześciorga": 6,
    "siedmiorga": 7,
    "ośmiorga": 8,
    "dziewięciorga": 9,
    "dziesięciorga": 10,
}


def _first_number_before_people(text: str) -> int | None:
    digit_match = re.search(
        r"(?:dla|na)\s+(\d{1,4})\s+(?:dzieci|os(?:ó|o)b|uczestnik)",
        text,
        flags=re.IGNORECASE,
    )
    if digit_match:
        return int(digit_match.group(1))
    lowered = text.casefold()
    for word, value in _NUMBER_WORDS.items():
        if re.search(rf"\b{word}\s+(?:dzieci|os(?:ó|o)b)", lowered):
            return value
    return None


def _budget(text: str) -> tuple[float | None, str]:
    match = re.search(
        r"(?:do|maksymalnie|budżet(?:em)?(?:\s+do)?)\s*"
        r"(\d+(?:[.,]\d{1,2})?)\s*(PLN|zł(?:otych)?)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None, "PLN"
    value = float(match.group(1).replace(",", "."))
    return value, "PLN"


def _deadline_text(text: str) -> str | None:
    time_match = re.search(
        r"\b(?:z\s+dostawą\s+)?(?:przed|do)\s+"
        r"(?:godziną\s+)?\d{1,2}(?::\d{2})?(?!\d)",
        text,
        flags=re.IGNORECASE,
    )
    if not time_match:
        return None
    deadline = time_match.group(0).strip()
    day_match = re.search(r"\b(dzisiaj|jutro|pojutrze|today|tomorrow)\b", text, re.IGNORECASE)
    return f"{day_match.group(0)}; {deadline}" if day_match else deadline


def deterministic_mission_fallback(transcript: str) -> MissionIntentDraft:
    """Extract the demo contract without a model or network dependency.

    It intentionally leaves unknown values as ``None`` instead of guessing.
    This keeps the deterministic workflow safe when local inference is down.
    """

    lowered = transcript.casefold()
    birthday = any(word in lowered for word in ("urodzin", "birthday"))
    budget, currency = _budget(transcript)

    categories: list[str] = []
    category_keywords = (
        ("snacks", ("jedzeni", "przekąs", "food", "snack")),
        ("drinks", ("napoj", "picie", "drink")),
        ("cake", ("tort", "cake")),
        ("decorations", ("dekorac", "decoration")),
        ("tableware", ("naczyni", "talerz", "kubk")),
    )
    for category, keywords in category_keywords:
        if any(keyword in lowered for keyword in keywords):
            categories.append(category)

    hard_constraints: list[str] = []
    if re.search(r"bez\s+orzech|no\s+nuts?|nut[- ]free", lowered):
        hard_constraints.append("nut_free")

    known_fields = sum(
        (
            birthday,
            _first_number_before_people(transcript) is not None,
            budget is not None,
            bool(categories),
            bool(hard_constraints),
            _deadline_text(transcript) is not None,
        )
    )
    confidence = min(0.82, 0.4 + known_fields * 0.07)

    return MissionIntentDraft(
        goal="prepare_birthday_party" if birthday else "commerce_mission",
        title="Przyjęcie urodzinowe" if birthday else "Misja zakupowa",
        participants=_first_number_before_people(transcript),
        budget=budget,
        currency=currency,  # type: ignore[arg-type]
        categories=categories,
        hard_constraints=hard_constraints,
        soft_preferences=[],
        deadline_text=_deadline_text(transcript),
        confidence=confidence,
    )


def _mission_semantic_issues(
    value: MissionIntentDraft,
    deterministic: MissionIntentDraft,
) -> list[str]:
    """Detect omissions of facts that can be proven without a model."""

    issues: list[str] = []
    if deterministic.participants is not None and value.participants != deterministic.participants:
        issues.append("participants")
    if deterministic.budget is not None and (
        value.budget is None or abs(value.budget - deterministic.budget) > 0.01
    ):
        issues.append("budget")
    if deterministic.currency != value.currency:
        issues.append("currency")
    if not set(deterministic.categories).issubset(value.categories):
        issues.append("categories")
    if not set(deterministic.hard_constraints).issubset(value.hard_constraints):
        issues.append("hard_constraints")
    if deterministic.deadline_text is not None and (
        value.deadline_text is None
        or value.deadline_text.casefold() != deterministic.deadline_text.casefold()
    ):
        issues.append("deadline_text")
    return issues


def _safe_error(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    return f"{type(exc).__name__}: {text[:180]}" if text else type(exc).__name__


class OllamaAdapter:
    """Native Ollama client with bounded concurrency and safe fallback."""

    def __init__(
        self,
        settings: AISettings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_ai_settings()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self.settings.ollama_base_url,
            timeout=httpx.Timeout(
                self.settings.ollama_request_timeout_seconds,
                connect=self.settings.ollama_connect_timeout_seconds,
            ),
            limits=httpx.Limits(
                max_connections=max(2, self.settings.ollama_max_concurrency),
                max_keepalive_connections=max(1, self.settings.ollama_max_concurrency),
            ),
            headers={"Accept": "application/json"},
        )
        self._semaphore = asyncio.Semaphore(self.settings.ollama_max_concurrency)

    async def __aenter__(self) -> "OllamaAdapter":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _options(self) -> dict[str, int | float]:
        return {
            "temperature": self.settings.ollama_temperature,
            "seed": self.settings.ollama_seed,
            "num_ctx": self.settings.ollama_num_ctx,
            "num_predict": self.settings.ollama_num_predict,
        }

    async def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with asyncio.timeout(self.settings.ollama_request_timeout_seconds):
            async with self._semaphore:
                response = await self._client.post("/api/chat", json=payload)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise OllamaProtocolError("response body is not an object")
        if body.get("done") is not True:
            raise OllamaProtocolError("non-streaming response is not complete")
        return body

    async def generate_structured(
        self,
        *,
        messages: Sequence[AIMessage],
        response_model: type[ResultT],
        fallback: Callable[[], ResultT],
    ) -> AIResult[ResultT]:
        payload = {
            "model": self.settings.ollama_model,
            "stream": False,
            "keep_alive": self.settings.ollama_keep_alive,
            "messages": [message.model_dump(exclude_none=True) for message in messages],
            "format": response_model.model_json_schema(),
            "options": self._options(),
        }
        try:
            body = await self._post_chat(payload)
            message = body.get("message")
            if not isinstance(message, dict):
                raise OllamaProtocolError("missing message object")
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                raise OllamaProtocolError("missing structured message content")
            value = response_model.model_validate_json(content)
            return AIResult(
                value=value,
                provider="ollama",
                model=self.settings.ollama_model,
            )
        except Exception as exc:
            return AIResult(
                value=fallback(),
                provider="fallback",
                model=self.settings.ollama_model,
                fallback_reason=_safe_error(exc),
            )

    async def extract_mission(
        self,
        transcript: str,
        *,
        locale: str = "pl-PL",
        timezone: str = "Europe/Warsaw",
        now: datetime,
    ) -> AIResult[MissionIntentDraft]:
        deterministic = deterministic_mission_fallback(transcript)
        system = (
            "Extract a commerce mission contract from the transcript. Preserve every "
            "hard constraint. Never invent a budget, participant count, or deadline. "
            "Return relative deadlines verbatim in deadline_text; do not convert them "
            "to a calendar date. Use canonical English category identifiers. The "
            "following facts were verified by deterministic parsing; copy every "
            "non-null scalar and every listed item exactly into the response: "
            f"{deterministic.model_dump_json()}. "
            f"Current time is {now.isoformat()}, timezone={timezone}, locale={locale}."
        )
        result = await self.generate_structured(
            messages=(
                AIMessage(role="system", content=system),
                AIMessage(role="user", content=transcript),
            ),
            response_model=MissionIntentDraft,
            fallback=lambda: deterministic,
        )
        if result.used_fallback:
            return result
        issues = _mission_semantic_issues(result.value, deterministic)
        if issues:
            return AIResult(
                value=deterministic,
                provider="fallback",
                model=self.settings.ollama_model,
                fallback_reason=("semantic validation rejected fields: " + ", ".join(issues)),
            )
        return result

    async def chat_with_tools(
        self,
        *,
        messages: Sequence[AIMessage],
        tools: Sequence[AITool],
        fallback: Callable[[], AIChatResponse],
    ) -> AIResult[AIChatResponse]:
        allowed_tools = {tool.name for tool in tools}
        payload = {
            "model": self.settings.ollama_model,
            "stream": False,
            "keep_alive": self.settings.ollama_keep_alive,
            "messages": [message.model_dump(exclude_none=True) for message in messages],
            "tools": [tool.as_ollama() for tool in tools],
            "options": self._options(),
        }
        try:
            body = await self._post_chat(payload)
            raw_message = body.get("message")
            if not isinstance(raw_message, dict):
                raise OllamaProtocolError("missing message object")

            tool_calls: list[AIToolCall] = []
            raw_tool_calls = raw_message.get("tool_calls", [])
            if not isinstance(raw_tool_calls, list):
                raise OllamaProtocolError("tool_calls is not an array")
            for raw_call in raw_tool_calls:
                if not isinstance(raw_call, dict):
                    raise OllamaProtocolError("tool call is not an object")
                function = raw_call.get("function")
                if not isinstance(function, dict):
                    raise OllamaProtocolError("tool call has no function")
                name = function.get("name")
                arguments = function.get("arguments")
                if not isinstance(name, str) or name not in allowed_tools:
                    raise OllamaProtocolError("model selected a non-allowlisted tool")
                if not isinstance(arguments, dict):
                    raise OllamaProtocolError("tool arguments are not an object")
                identifier = raw_call.get("id")
                tool_calls.append(
                    AIToolCall(
                        id=identifier if isinstance(identifier, str) else None,
                        name=name,
                        arguments=arguments,
                    )
                )

            result = AIChatResponse(
                content=(
                    raw_message.get("content")
                    if isinstance(raw_message.get("content"), str)
                    else ""
                ),
                tool_calls=tool_calls,
            )
            return AIResult(
                value=result,
                provider="ollama",
                model=self.settings.ollama_model,
            )
        except Exception as exc:
            return AIResult(
                value=fallback(),
                provider="fallback",
                model=self.settings.ollama_model,
                fallback_reason=_safe_error(exc),
            )

    async def health(self) -> AIHealth:
        try:
            async with asyncio.timeout(self.settings.ollama_request_timeout_seconds):
                async with self._semaphore:
                    version_response = await self._client.get("/api/version")
                    version_response.raise_for_status()
                    tags_response = await self._client.get("/api/tags")
                    tags_response.raise_for_status()

            version_body = version_response.json()
            tags_body = tags_response.json()
            version = version_body.get("version") if isinstance(version_body, dict) else None
            raw_models = tags_body.get("models", []) if isinstance(tags_body, dict) else []
            model_names = {
                item.get("name")
                for item in raw_models
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            }
            model_available = self.settings.ollama_model in model_names

            model_loaded = False
            detail: str | None = None
            try:
                async with asyncio.timeout(self.settings.ollama_request_timeout_seconds):
                    async with self._semaphore:
                        ps_response = await self._client.get("/api/ps")
                ps_response.raise_for_status()
                ps_body = ps_response.json()
                loaded_models = ps_body.get("models", []) if isinstance(ps_body, dict) else []
                model_loaded = any(
                    isinstance(item, dict) and item.get("name") == self.settings.ollama_model
                    for item in loaded_models
                )
            except Exception as exc:
                detail = f"process status unavailable: {_safe_error(exc)}"

            return AIHealth(
                status="available" if model_available else "degraded",
                version=version if isinstance(version, str) else None,
                model=self.settings.ollama_model,
                model_available=model_available,
                model_loaded=model_loaded,
                detail=(
                    detail
                    if model_available
                    else f"model {self.settings.ollama_model!r} is not installed"
                ),
            )
        except Exception as exc:
            return AIHealth(
                status="unavailable",
                model=self.settings.ollama_model,
                detail=_safe_error(exc),
            )
