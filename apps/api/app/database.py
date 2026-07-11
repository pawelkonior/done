"""Small, durable SQLite persistence layer used by the demo workflow."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    locale TEXT NOT NULL,
    currency TEXT NOT NULL,
    timezone TEXT NOT NULL,
    autonomy_level TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Profile-specific data is kept outside the base users table so this is an
-- additive migration for databases created by earlier demo versions.
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    email TEXT NOT NULL UNIQUE,
    delivery_address_json TEXT NOT NULL,
    payment_method_json TEXT NOT NULL,
    default_constraints_json TEXT NOT NULL,
    contact_preference TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    voice_language TEXT NOT NULL,
    confirmation_voice_enabled INTEGER NOT NULL DEFAULT 1,
    safe_recovery_enabled INTEGER NOT NULL DEFAULT 1,
    approval_policy TEXT NOT NULL,
    approval_threshold_cents INTEGER NOT NULL DEFAULT 0
        CHECK(approval_threshold_cents >= 0),
    approval_threshold_currency TEXT NOT NULL,
    notifications_enabled INTEGER NOT NULL DEFAULT 1,
    preferred_merchant_ids_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS merchants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    reliability_score REAL NOT NULL,
    payment_success_rate REAL NOT NULL,
    delivery_success_rate REAL NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    merchant_id TEXT NOT NULL REFERENCES merchants(id),
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    price_cents INTEGER NOT NULL CHECK(price_cents >= 0),
    currency TEXT NOT NULL,
    stock INTEGER NOT NULL CHECK(stock >= 0),
    allergens_json TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    rating REAL NOT NULL,
    delivery_class TEXT NOT NULL,
    substitute_group TEXT,
    nut_free INTEGER NOT NULL DEFAULT 0,
    image_url TEXT
);

CREATE TABLE IF NOT EXISTS missions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    subtitle TEXT NOT NULL,
    raw_voice_transcript TEXT NOT NULL,
    input_mode TEXT NOT NULL,
    status TEXT NOT NULL,
    current_step INTEGER NOT NULL,
    total_steps INTEGER NOT NULL,
    mission_type TEXT NOT NULL,
    budget_limit_cents INTEGER NOT NULL,
    currency TEXT NOT NULL,
    deadline TEXT NOT NULL,
    risk_level INTEGER NOT NULL,
    requires_approval INTEGER NOT NULL,
    locale TEXT NOT NULL,
    timezone TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    summary_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS mission_contracts (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    goal TEXT NOT NULL,
    participants_json TEXT NOT NULL,
    hard_constraints_json TEXT NOT NULL,
    soft_preferences_json TEXT NOT NULL,
    budget_limit_cents INTEGER NOT NULL,
    currency TEXT NOT NULL,
    deadline TEXT NOT NULL,
    approval_policy TEXT NOT NULL,
    allowed_categories_json TEXT NOT NULL,
    forbidden_categories_json TEXT NOT NULL,
    confidence REAL NOT NULL,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(mission_id, version)
);

CREATE TABLE IF NOT EXISTS mission_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    severity TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS delivery_options (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    merchant_id TEXT NOT NULL REFERENCES merchants(id),
    label TEXT NOT NULL,
    delivery_at TEXT NOT NULL,
    cost_cents INTEGER NOT NULL,
    confidence REAL NOT NULL,
    selected INTEGER NOT NULL DEFAULT 0,
    available INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS baskets (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    merchant_id TEXT NOT NULL REFERENCES merchants(id),
    delivery_option_id TEXT REFERENCES delivery_options(id),
    subtotal_cents INTEGER NOT NULL,
    delivery_cost_cents INTEGER NOT NULL,
    total_cents INTEGER NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS basket_items (
    id TEXT PRIMARY KEY,
    basket_id TEXT NOT NULL REFERENCES baskets(id) ON DELETE CASCADE,
    product_id TEXT NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    unit_price_cents INTEGER NOT NULL,
    substitution_allowed INTEGER NOT NULL DEFAULT 1,
    replaced_product_id TEXT REFERENCES products(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approval_requests (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    approval_type TEXT NOT NULL,
    question TEXT NOT NULL,
    options_json TEXT NOT NULL,
    status TEXT NOT NULL,
    selected_option TEXT,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS payment_attempts (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    merchant_id TEXT NOT NULL REFERENCES merchants(id),
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL,
    decline_code TEXT,
    retry_number INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS failure_injections (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    failure_type TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    consumed_at TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL UNIQUE REFERENCES missions(id) ON DELETE CASCADE,
    basket_id TEXT NOT NULL REFERENCES baskets(id),
    confirmation_code TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    total_cents INTEGER NOT NULL,
    currency TEXT NOT NULL,
    delivery_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_missions_status ON missions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_events_mission_cursor ON mission_events(mission_id, id);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category, merchant_id);
CREATE INDEX IF NOT EXISTS idx_approvals_mission_status ON approval_requests(mission_id, status);
CREATE INDEX IF NOT EXISTS idx_payments_mission_created ON payment_attempts(mission_id, created_at);
CREATE INDEX IF NOT EXISTS idx_failures_mission_status ON failure_injections(mission_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_profiles_email ON user_profiles(email);
"""


MERCHANTS = [
    ("merchant-a", "Budget Market", 0.82, 0.86, 0.80, 1),
    ("merchant-b", "Party Market", 0.94, 0.96, 0.95, 1),
    ("merchant-c", "Premium Express", 0.99, 0.99, 0.99, 1),
]


# Products used by the deterministic planner plus a few alternatives for the UI.
# Prices are represented as integer grosz values throughout the database.
PRODUCTS = [
    ("snack-pretzels", "merchant-b", "SN-001", "Mini precle", "Pieczone mini precle dla dzieci.", "snacks", 699, "PLN", 50, [], ["party", "savory", "nut-free"], 4.7, "ambient", "savory-kids", 1, None),
    ("snack-crackers", "merchant-b", "SN-002", "Krakersy kukurydziane", "Bezglutenowe krakersy kukurydziane.", "snacks", 749, "PLN", 50, [], ["party", "savory", "nut-free"], 4.8, "ambient", "savory-kids", 1, None),
    ("snack-popcorn", "merchant-a", "SN-003", "Popcorn lekko solony", "Duża paczka popcornu.", "snacks", 549, "PLN", 35, [], ["party", "nut-free"], 4.4, "ambient", "savory-kids", 1, None),
    ("drink-apple", "merchant-b", "DR-001", "Sok jabłkowy 1 l", "Sok jabłkowy bez dodatku cukru.", "drinks", 799, "PLN", 60, [], ["kids", "nut-free"], 4.8, "ambient", "juice", 1, None),
    ("drink-water", "merchant-b", "DR-002", "Woda niegazowana 1,5 l", "Naturalna woda źródlana.", "drinks", 329, "PLN", 80, [], ["kids", "nut-free"], 4.7, "ambient", "water", 1, None),
    ("cake-vanilla", "merchant-b", "CA-001", "Tort waniliowy bez orzechów", "Tort na 12 porcji z deklaracją nut-free.", "cake", 4999, "PLN", 8, ["milk", "eggs", "gluten"], ["birthday", "nut-free"], 4.9, "chilled", "birthday-cake", 1, None),
    ("cake-chocolate", "merchant-c", "CA-002", "Tort czekoladowy premium", "Tort na 12 porcji, produkcja bez orzechów.", "cake", 6999, "PLN", 5, ["milk", "eggs", "gluten"], ["birthday", "nut-free"], 4.9, "chilled", "birthday-cake", 1, None),
    ("decor-balloons", "merchant-b", "DE-001", "Balony biodegradowalne", "Kolorowy zestaw 20 balonów.", "decorations", 1999, "PLN", 25, [], ["birthday", "plastic-free"], 4.7, "ambient", "balloons", 1, None),
    ("decor-banner", "merchant-b", "DE-002", "Girlanda Happy Birthday", "Papierowa girlanda urodzinowa.", "decorations", 1499, "PLN", 30, [], ["birthday", "plastic-free"], 4.6, "ambient", "banner", 1, None),
    ("table-plates", "merchant-b", "TA-001", "Papierowe talerzyki", "Komplet 12 papierowych talerzyków.", "tableware", 1199, "PLN", 40, [], ["party", "plastic-free"], 4.5, "ambient", "plates", 1, None),
    ("table-cups", "merchant-b", "TA-002", "Papierowe kubki", "Komplet 12 papierowych kubków.", "tableware", 1099, "PLN", 40, [], ["party", "plastic-free"], 4.5, "ambient", "cups", 1, None),
    ("napkins-color", "merchant-b", "NA-001", "Kolorowe serwetki", "Paczka 20 serwetek.", "napkins", 899, "PLN", 45, [], ["party"], 4.6, "ambient", "napkins", 1, None),
    ("candles-ten", "merchant-b", "CN-001", "Świeczki urodzinowe", "Zestaw 10 kolorowych świeczek.", "candles", 799, "PLN", 35, [], ["birthday"], 4.5, "ambient", "candles", 1, None),
    ("party-bags", "merchant-c", "PB-001", "Papierowe torby prezentowe", "Zestaw 10 papierowych torebek.", "party bags", 2499, "PLN", 12, [], ["birthday", "plastic-free"], 4.8, "ambient", "party-bags", 1, None),
]


class Database:
    """Connection-per-operation SQLite wrapper safe for TestClient threads."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def initialize(self) -> None:
        with self._write_lock, self.connect() as connection:
            if self.path != ":memory:":
                connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA)
            self._seed_reference_data(connection)
            connection.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
            connection = self.connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    @contextmanager
    def reader(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    def reset(self) -> None:
        """Clear demo state and restore all reference inventory and prices."""

        with self.transaction() as connection:
            for table in (
                "orders",
                "failure_injections",
                "payment_attempts",
                "approval_requests",
                "basket_items",
                "baskets",
                "delivery_options",
                "mission_events",
                "mission_contracts",
                "missions",
                "user_settings",
                "user_profiles",
                "products",
                "merchants",
                "users",
            ):
                connection.execute(f"DELETE FROM {table}")
            connection.execute("DELETE FROM sqlite_sequence WHERE name = 'mission_events'")
            self._seed_reference_data(connection)

    @staticmethod
    def _seed_reference_data(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO users
                (id, name, locale, currency, timezone, autonomy_level, created_at)
            VALUES
                ('demo-user', 'Pawel', 'pl-PL', 'PLN', 'Europe/Warsaw', 'balanced',
                 '2026-01-01T00:00:00+00:00')
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO user_profiles
                (user_id, email, delivery_address_json, payment_method_json,
                 default_constraints_json, contact_preference, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "demo-user",
                "pawel@example.com",
                json.dumps(
                    {
                        "label": "Home",
                        "line1": "ul. Marszałkowska 1",
                        "city": "Warsaw",
                        "postal_code": "00-001",
                        "country": "PL",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "token": "pm_demo_visa_4242",
                        "brand": "Visa",
                        "last4": "4242",
                        "expiry_month": 12,
                        "expiry_year": 2028,
                        "is_demo": True,
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    [
                        "Never exceed the mission budget",
                        "Never relax allergen constraints",
                        "Deliver before the stated deadline",
                    ],
                    ensure_ascii=False,
                ),
                "only_when_needed",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO user_settings
                (user_id, voice_language, confirmation_voice_enabled,
                 safe_recovery_enabled, approval_policy,
                 approval_threshold_cents, approval_threshold_currency,
                 notifications_enabled, preferred_merchant_ids_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "demo-user",
                "en-PL",
                1,
                1,
                "always",
                0,
                "PLN",
                1,
                json.dumps(["merchant-b"]),
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.executemany(
            """
            INSERT OR IGNORE INTO merchants
                (id, name, reliability_score, payment_success_rate,
                 delivery_success_rate, active)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            MERCHANTS,
        )
        connection.executemany(
            """
            INSERT OR IGNORE INTO products
                (id, merchant_id, sku, name, description, category, price_cents,
                 currency, stock, allergens_json, tags_json, rating,
                 delivery_class, substitute_group, nut_free, image_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    *product[:9],
                    json.dumps(product[9], ensure_ascii=False),
                    json.dumps(product[10], ensure_ascii=False),
                    *product[11:],
                )
                for product in PRODUCTS
            ],
        )
