"""Inbound mission workflow port owned by the application layer."""

from __future__ import annotations

from typing import Any, Protocol

from app.domain.mission.policies import MissionExecutionPolicy


class MissionWorkflowPort(Protocol):
    def interpret_transcript(
        self, transcript: str, locale: str, timezone: str
    ) -> dict[str, Any]: ...

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
    ) -> dict[str, Any]: ...
