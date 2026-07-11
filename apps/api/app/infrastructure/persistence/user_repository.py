"""SQLite adapter for the UserApplicationService persistence port."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from app.application.user_service import MerchantSummary, UserNotFoundError, UserStats
from app.database import Database
from app.domain.common import DomainError, Money
from app.domain.user.model import (
    ApprovalPolicy,
    ContactPreference,
    DeliveryAddress,
    PaymentMethod,
    UserProfile,
    UserSettings,
)


def _load_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class SQLiteUserRepository:
    def __init__(self, database: Database):
        self._database = database

    def get_profile(self, user_id: str) -> UserProfile:
        with self._database.reader() as connection:
            row = connection.execute(
                """
                SELECT u.id, u.name, u.locale, u.currency, u.timezone,
                       u.autonomy_level, p.email, p.delivery_address_json,
                       p.payment_method_json, p.default_constraints_json,
                       p.contact_preference
                FROM users u
                JOIN user_profiles p ON p.user_id = u.id
                WHERE u.id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            raise UserNotFoundError(user_id)
        address = _load_json(row["delivery_address_json"], {})
        payment = _load_json(row["payment_method_json"], {})
        return UserProfile(
            id=row["id"],
            name=row["name"],
            email=row["email"],
            locale=row["locale"],
            currency=row["currency"],
            timezone=row["timezone"],
            autonomy_level=row["autonomy_level"],
            delivery_address=DeliveryAddress(**address),
            payment_method=PaymentMethod(**payment),
            default_constraints=tuple(
                _load_json(row["default_constraints_json"], [])
            ),
            contact_preference=ContactPreference(row["contact_preference"]),
        )

    def save_profile(self, profile: UserProfile) -> None:
        try:
            with self._database.transaction() as connection:
                self._write_profile(connection, profile)
        except sqlite3.IntegrityError as exc:
            raise DomainError("The profile conflicts with existing user data") from exc

    def save_profile_and_settings(
        self, profile: UserProfile, settings: UserSettings
    ) -> None:
        try:
            with self._database.transaction() as connection:
                self._write_profile(connection, profile)
                self._write_settings(connection, settings)
        except sqlite3.IntegrityError as exc:
            raise DomainError("The profile conflicts with existing user data") from exc

    def get_settings(self, user_id: str) -> UserSettings:
        with self._database.reader() as connection:
            row = connection.execute(
                "SELECT * FROM user_settings WHERE user_id = ?", (user_id,)
            ).fetchone()
        if row is None:
            raise UserNotFoundError(user_id)
        return UserSettings(
            user_id=row["user_id"],
            voice_language=row["voice_language"],
            confirmation_voice_enabled=bool(row["confirmation_voice_enabled"]),
            safe_recovery_enabled=bool(row["safe_recovery_enabled"]),
            approval_policy=ApprovalPolicy(row["approval_policy"]),
            approval_threshold=Money(
                row["approval_threshold_cents"],
                row["approval_threshold_currency"],
            ),
            notifications_enabled=bool(row["notifications_enabled"]),
            preferred_merchant_ids=tuple(
                _load_json(row["preferred_merchant_ids_json"], [])
            ),
        )

    def save_settings(self, settings: UserSettings) -> None:
        with self._database.transaction() as connection:
            self._write_settings(connection, settings)

    def get_stats(self, user_id: str) -> UserStats:
        with self._database.reader() as connection:
            user = connection.execute(
                "SELECT currency FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if user is None:
                raise UserNotFoundError(user_id)
            mission_count = connection.execute(
                "SELECT COUNT(*) AS count FROM missions WHERE user_id = ?",
                (user_id,),
            ).fetchone()["count"]
            recoveries = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM failure_injections f
                JOIN missions m ON m.id = f.mission_id
                WHERE m.user_id = ? AND f.status = 'consumed'
                  AND f.failure_type IN (
                      'product_unavailable', 'payment_soft_decline',
                      'price_changed', 'delivery_slot_lost'
                  )
                """,
                (user_id,),
            ).fetchone()["count"]
            saved_cents = connection.execute(
                """
                SELECT COALESCE(SUM(
                    CASE
                        WHEN m.budget_limit_cents > b.total_cents
                        THEN m.budget_limit_cents - b.total_cents
                        ELSE 0
                    END
                ), 0) AS saved_cents
                FROM missions m
                JOIN baskets b ON b.id = (
                    SELECT latest.id FROM baskets latest
                    WHERE latest.mission_id = m.id
                    ORDER BY latest.created_at DESC LIMIT 1
                )
                WHERE m.user_id = ? AND m.status = 'completed'
                  AND m.currency = ?
                """,
                (user_id, user["currency"]),
            ).fetchone()["saved_cents"]
        return UserStats(
            missions=int(mission_count),
            recoveries=int(recoveries),
            saved=Money(int(saved_cents), user["currency"]),
        )

    def list_merchants(self) -> tuple[MerchantSummary, ...]:
        with self._database.reader() as connection:
            rows = connection.execute(
                """
                SELECT id, name, reliability_score, payment_success_rate,
                       delivery_success_rate, active
                FROM merchants
                ORDER BY active DESC, reliability_score DESC, name ASC
                """
            ).fetchall()
        return tuple(
            MerchantSummary(
                id=row["id"],
                name=row["name"],
                reliability_score=float(row["reliability_score"]),
                payment_success_rate=float(row["payment_success_rate"]),
                delivery_success_rate=float(row["delivery_success_rate"]),
                active=bool(row["active"]),
            )
            for row in rows
        )

    @staticmethod
    def _write_profile(connection: sqlite3.Connection, profile: UserProfile) -> None:
        updated = connection.execute(
            """
            UPDATE users
            SET name = ?, locale = ?, currency = ?, timezone = ?, autonomy_level = ?
            WHERE id = ?
            """,
            (
                profile.name,
                profile.locale,
                profile.currency,
                profile.timezone,
                profile.autonomy_level,
                profile.id,
            ),
        )
        if updated.rowcount != 1:
            raise UserNotFoundError(profile.id)
        profile_updated = connection.execute(
            """
            UPDATE user_profiles
            SET email = ?, delivery_address_json = ?, payment_method_json = ?,
                default_constraints_json = ?, contact_preference = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (
                profile.email,
                json.dumps(
                    {
                        "label": profile.delivery_address.label,
                        "line1": profile.delivery_address.line1,
                        "city": profile.delivery_address.city,
                        "postal_code": profile.delivery_address.postal_code,
                        "country": profile.delivery_address.country,
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "token": profile.payment_method.token,
                        "brand": profile.payment_method.brand,
                        "last4": profile.payment_method.last4,
                        "expiry_month": profile.payment_method.expiry_month,
                        "expiry_year": profile.payment_method.expiry_year,
                        "is_demo": profile.payment_method.is_demo,
                    },
                    ensure_ascii=False,
                ),
                json.dumps(profile.default_constraints, ensure_ascii=False),
                profile.contact_preference.value,
                _now(),
                profile.id,
            ),
        )
        if profile_updated.rowcount != 1:
            raise UserNotFoundError(profile.id)

    @staticmethod
    def _write_settings(
        connection: sqlite3.Connection, settings: UserSettings
    ) -> None:
        updated = connection.execute(
            """
            UPDATE user_settings
            SET voice_language = ?, confirmation_voice_enabled = ?,
                safe_recovery_enabled = ?, approval_policy = ?,
                approval_threshold_cents = ?, approval_threshold_currency = ?,
                notifications_enabled = ?, preferred_merchant_ids_json = ?,
                updated_at = ?
            WHERE user_id = ?
            """,
            (
                settings.voice_language,
                int(settings.confirmation_voice_enabled),
                int(settings.safe_recovery_enabled),
                settings.approval_policy.value,
                settings.approval_threshold.minor,
                settings.approval_threshold.currency,
                int(settings.notifications_enabled),
                json.dumps(settings.preferred_merchant_ids),
                _now(),
                settings.user_id,
            ),
        )
        if updated.rowcount != 1:
            raise UserNotFoundError(settings.user_id)
