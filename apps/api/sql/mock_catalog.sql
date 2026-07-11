-- Standalone SQLite mock catalog for local development and demos.
-- Money is stored in minor units: 1299 means 12.99 PLN.
-- The script is transactional and idempotent, so it is safe to run repeatedly.

PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS catalog_stores (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    country_code TEXT NOT NULL DEFAULT 'PL'
        CHECK (length(country_code) = 2),
    status TEXT NOT NULL
        CHECK (status IN ('open', 'temporarily_closed', 'inactive')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS catalog_products (
    id TEXT PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    brand TEXT NOT NULL,
    category TEXT NOT NULL,
    unit_label TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- One row represents one product offer at one store. This allows the same
-- product to have a different price and inventory status in every store.
CREATE TABLE IF NOT EXISTS catalog_offers (
    store_id TEXT NOT NULL
        REFERENCES catalog_stores(id) ON DELETE CASCADE,
    product_id TEXT NOT NULL
        REFERENCES catalog_products(id) ON DELETE CASCADE,
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    currency TEXT NOT NULL DEFAULT 'PLN' CHECK (length(currency) = 3),
    quantity INTEGER NOT NULL CHECK (quantity >= 0),
    availability_status TEXT NOT NULL
        CHECK (
            availability_status IN (
                'available',
                'low_stock',
                'out_of_stock',
                'discontinued'
            )
        ),
    is_available INTEGER GENERATED ALWAYS AS (
        CASE
            WHEN availability_status IN ('available', 'low_stock')
                 AND quantity > 0
            THEN 1
            ELSE 0
        END
    ) STORED,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (store_id, product_id),
    CHECK (
        (availability_status = 'available' AND quantity >= 6)
        OR (availability_status = 'low_stock' AND quantity BETWEEN 1 AND 5)
        OR (availability_status IN ('out_of_stock', 'discontinued')
            AND quantity = 0)
    )
);

CREATE INDEX IF NOT EXISTS idx_catalog_products_category
    ON catalog_products(category, name);
CREATE INDEX IF NOT EXISTS idx_catalog_offers_product_price
    ON catalog_offers(product_id, price_cents);
CREATE INDEX IF NOT EXISTS idx_catalog_offers_status
    ON catalog_offers(availability_status, store_id);

INSERT INTO catalog_stores
    (id, slug, name, city, country_code, status, created_at, updated_at)
VALUES
    ('store-budget', 'budget-market', 'Budget Market', 'Warsaw', 'PL', 'open',
     '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z'),
    ('store-party', 'party-market', 'Party Market', 'Warsaw', 'PL', 'open',
     '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z'),
    ('store-premium', 'premium-express', 'Premium Express', 'Warsaw', 'PL', 'open',
     '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z'),
    ('store-eco', 'eco-corner', 'Eco Corner', 'Warsaw', 'PL', 'open',
     '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z'),
    ('store-weekend', 'weekend-outlet', 'Weekend Outlet', 'Warsaw', 'PL',
     'temporarily_closed', '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z')
ON CONFLICT(id) DO UPDATE SET
    slug = excluded.slug,
    name = excluded.name,
    city = excluded.city,
    country_code = excluded.country_code,
    status = excluded.status,
    updated_at = excluded.updated_at;

INSERT INTO catalog_products
    (id, sku, name, brand, category, unit_label, description, created_at, updated_at)
VALUES
    ('product-water', 'MOCK-DR-001', 'Still water 1.5 l', 'Clear Spring',
     'drinks', '1.5 l bottle', 'Natural still spring water.',
     '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z'),
    ('product-apple-juice', 'MOCK-DR-002', 'Apple juice 1 l', 'Orchard Day',
     'drinks', '1 l carton', 'Apple juice with no added sugar.',
     '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z'),
    ('product-orange-juice', 'MOCK-DR-003', 'Orange juice 1 l', 'Sunny Grove',
     'drinks', '1 l carton', 'Pasteurized orange juice.',
     '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z'),
    ('product-lemonade', 'MOCK-DR-004', 'Craft lemonade 750 ml', 'Lemon Lab',
     'drinks', '750 ml bottle', 'Sparkling lemonade with lemon juice.',
     '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z'),
    ('product-pretzels', 'MOCK-SN-001', 'Mini pretzels', 'Party Bites',
     'snacks', '200 g bag', 'Oven-baked salted mini pretzels.',
     '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z'),
    ('product-crackers', 'MOCK-SN-002', 'Corn crackers', 'Crispy Field',
     'snacks', '150 g bag', 'Gluten-free corn crackers.',
     '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z'),
    ('product-popcorn', 'MOCK-SN-003', 'Lightly salted popcorn', 'Pop Joy',
     'snacks', '120 g bag', 'Ready-to-eat lightly salted popcorn.',
     '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z'),
    ('product-gummies', 'MOCK-SN-004', 'Fruit gummies', 'Happy Fruit',
     'snacks', '180 g bag', 'Assorted fruit-flavoured gummies.',
     '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z'),
    ('product-vanilla-cake', 'MOCK-CA-001', 'Vanilla birthday cake', 'Sweet Day',
     'cakes', '12 servings', 'Vanilla cake decorated for a birthday party.',
     '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z'),
    ('product-chocolate-cake', 'MOCK-CA-002', 'Chocolate birthday cake', 'Cocoa House',
     'cakes', '12 servings', 'Chocolate layer cake with cocoa cream.',
     '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z'),
    ('product-cupcakes', 'MOCK-CA-003', 'Vanilla cupcakes', 'Sweet Day',
     'cakes', 'box of 12', 'Twelve vanilla cupcakes with colourful frosting.',
     '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z'),
    ('product-balloons', 'MOCK-DE-001', 'Biodegradable balloons', 'Green Party',
     'decorations', 'pack of 20', 'Assorted biodegradable party balloons.',
     '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z'),
    ('product-banner', 'MOCK-DE-002', 'Happy Birthday banner', 'Paper Party',
     'decorations', '1 banner', 'Reusable paper birthday banner.',
     '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z'),
    ('product-confetti', 'MOCK-DE-003', 'Paper confetti', 'Paper Party',
     'decorations', '50 g pack', 'Plastic-free colourful paper confetti.',
     '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z'),
    ('product-plates', 'MOCK-TA-001', 'Paper plates', 'Table Ready',
     'tableware', 'pack of 12', 'Twelve disposable paper plates.',
     '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z'),
    ('product-cups', 'MOCK-TA-002', 'Paper cups', 'Table Ready',
     'tableware', 'pack of 12', 'Twelve disposable paper cups.',
     '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z'),
    ('product-napkins', 'MOCK-TA-003', 'Colourful napkins', 'Table Ready',
     'tableware', 'pack of 20', 'Twenty colourful paper napkins.',
     '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z'),
    ('product-tablecloth', 'MOCK-TA-004', 'Paper tablecloth', 'Table Ready',
     'tableware', '1 tablecloth', 'Disposable paper tablecloth, 120 x 180 cm.',
     '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z'),
    ('product-candles', 'MOCK-PA-001', 'Birthday candles', 'Wish Makers',
     'party_supplies', 'pack of 10', 'Ten colourful birthday candles.',
     '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z'),
    ('product-party-bags', 'MOCK-PA-002', 'Paper party bags', 'Paper Party',
     'party_supplies', 'pack of 10', 'Ten recyclable paper party bags.',
     '2026-07-11T10:00:00Z', '2026-07-11T10:00:00Z')
ON CONFLICT(id) DO UPDATE SET
    sku = excluded.sku,
    name = excluded.name,
    brand = excluded.brand,
    category = excluded.category,
    unit_label = excluded.unit_label,
    description = excluded.description,
    updated_at = excluded.updated_at;

INSERT INTO catalog_offers
    (store_id, product_id, price_cents, currency, quantity,
     availability_status, updated_at)
VALUES
    -- Budget Market
    ('store-budget', 'product-water', 299, 'PLN', 120, 'available', '2026-07-11T10:00:00Z'),
    ('store-budget', 'product-apple-juice', 699, 'PLN', 30, 'available', '2026-07-11T10:00:00Z'),
    ('store-budget', 'product-orange-juice', 749, 'PLN', 0, 'out_of_stock', '2026-07-11T10:00:00Z'),
    ('store-budget', 'product-pretzels', 599, 'PLN', 14, 'available', '2026-07-11T10:00:00Z'),
    ('store-budget', 'product-crackers', 649, 'PLN', 4, 'low_stock', '2026-07-11T10:00:00Z'),
    ('store-budget', 'product-popcorn', 449, 'PLN', 35, 'available', '2026-07-11T10:00:00Z'),
    ('store-budget', 'product-gummies', 899, 'PLN', 0, 'out_of_stock', '2026-07-11T10:00:00Z'),
    ('store-budget', 'product-balloons', 1699, 'PLN', 0, 'out_of_stock', '2026-07-11T10:00:00Z'),
    ('store-budget', 'product-plates', 899, 'PLN', 20, 'available', '2026-07-11T10:00:00Z'),
    ('store-budget', 'product-cups', 799, 'PLN', 20, 'available', '2026-07-11T10:00:00Z'),
    ('store-budget', 'product-napkins', 599, 'PLN', 5, 'low_stock', '2026-07-11T10:00:00Z'),
    ('store-budget', 'product-tablecloth', 1099, 'PLN', 0, 'discontinued', '2026-07-11T10:00:00Z'),
    ('store-budget', 'product-candles', 599, 'PLN', 18, 'available', '2026-07-11T10:00:00Z'),

    -- Party Market
    ('store-party', 'product-water', 329, 'PLN', 80, 'available', '2026-07-11T10:00:00Z'),
    ('store-party', 'product-apple-juice', 799, 'PLN', 60, 'available', '2026-07-11T10:00:00Z'),
    ('store-party', 'product-orange-juice', 829, 'PLN', 12, 'available', '2026-07-11T10:00:00Z'),
    ('store-party', 'product-pretzels', 699, 'PLN', 50, 'available', '2026-07-11T10:00:00Z'),
    ('store-party', 'product-crackers', 749, 'PLN', 50, 'available', '2026-07-11T10:00:00Z'),
    ('store-party', 'product-popcorn', 549, 'PLN', 2, 'low_stock', '2026-07-11T10:00:00Z'),
    ('store-party', 'product-gummies', 999, 'PLN', 10, 'available', '2026-07-11T10:00:00Z'),
    ('store-party', 'product-vanilla-cake', 4999, 'PLN', 8, 'available', '2026-07-11T10:00:00Z'),
    ('store-party', 'product-balloons', 1999, 'PLN', 25, 'available', '2026-07-11T10:00:00Z'),
    ('store-party', 'product-banner', 1499, 'PLN', 30, 'available', '2026-07-11T10:00:00Z'),
    ('store-party', 'product-plates', 1199, 'PLN', 40, 'available', '2026-07-11T10:00:00Z'),
    ('store-party', 'product-cups', 1099, 'PLN', 40, 'available', '2026-07-11T10:00:00Z'),
    ('store-party', 'product-napkins', 899, 'PLN', 45, 'available', '2026-07-11T10:00:00Z'),
    ('store-party', 'product-candles', 799, 'PLN', 35, 'available', '2026-07-11T10:00:00Z'),
    ('store-party', 'product-party-bags', 2299, 'PLN', 0, 'out_of_stock', '2026-07-11T10:00:00Z'),

    -- Premium Express
    ('store-premium', 'product-water', 449, 'PLN', 30, 'available', '2026-07-11T10:00:00Z'),
    ('store-premium', 'product-apple-juice', 999, 'PLN', 4, 'low_stock', '2026-07-11T10:00:00Z'),
    ('store-premium', 'product-lemonade', 1299, 'PLN', 12, 'available', '2026-07-11T10:00:00Z'),
    ('store-premium', 'product-gummies', 1499, 'PLN', 7, 'available', '2026-07-11T10:00:00Z'),
    ('store-premium', 'product-vanilla-cake', 5999, 'PLN', 0, 'out_of_stock', '2026-07-11T10:00:00Z'),
    ('store-premium', 'product-chocolate-cake', 6999, 'PLN', 5, 'low_stock', '2026-07-11T10:00:00Z'),
    ('store-premium', 'product-cupcakes', 3999, 'PLN', 7, 'available', '2026-07-11T10:00:00Z'),
    ('store-premium', 'product-balloons', 2499, 'PLN', 11, 'available', '2026-07-11T10:00:00Z'),
    ('store-premium', 'product-confetti', 1299, 'PLN', 0, 'discontinued', '2026-07-11T10:00:00Z'),
    ('store-premium', 'product-tablecloth', 1999, 'PLN', 9, 'available', '2026-07-11T10:00:00Z'),
    ('store-premium', 'product-party-bags', 2499, 'PLN', 12, 'available', '2026-07-11T10:00:00Z'),

    -- Eco Corner
    ('store-eco', 'product-water', 499, 'PLN', 18, 'available', '2026-07-11T10:00:00Z'),
    ('store-eco', 'product-apple-juice', 949, 'PLN', 6, 'available', '2026-07-11T10:00:00Z'),
    ('store-eco', 'product-crackers', 899, 'PLN', 8, 'available', '2026-07-11T10:00:00Z'),
    ('store-eco', 'product-popcorn', 749, 'PLN', 0, 'out_of_stock', '2026-07-11T10:00:00Z'),
    ('store-eco', 'product-balloons', 2299, 'PLN', 7, 'available', '2026-07-11T10:00:00Z'),
    ('store-eco', 'product-banner', 1399, 'PLN', 3, 'low_stock', '2026-07-11T10:00:00Z'),
    ('store-eco', 'product-confetti', 1099, 'PLN', 10, 'available', '2026-07-11T10:00:00Z'),
    ('store-eco', 'product-plates', 1399, 'PLN', 8, 'available', '2026-07-11T10:00:00Z'),
    ('store-eco', 'product-cups', 1299, 'PLN', 0, 'out_of_stock', '2026-07-11T10:00:00Z'),
    ('store-eco', 'product-tablecloth', 1699, 'PLN', 6, 'available', '2026-07-11T10:00:00Z'),

    -- Weekend Outlet: offers have stock, but the store is temporarily closed.
    ('store-weekend', 'product-water', 279, 'PLN', 50, 'available', '2026-07-11T10:00:00Z'),
    ('store-weekend', 'product-pretzels', 499, 'PLN', 20, 'available', '2026-07-11T10:00:00Z'),
    ('store-weekend', 'product-balloons', 1299, 'PLN', 5, 'low_stock', '2026-07-11T10:00:00Z'),
    ('store-weekend', 'product-plates', 749, 'PLN', 30, 'available', '2026-07-11T10:00:00Z'),
    ('store-weekend', 'product-napkins', 499, 'PLN', 30, 'available', '2026-07-11T10:00:00Z')
ON CONFLICT(store_id, product_id) DO UPDATE SET
    price_cents = excluded.price_cents,
    currency = excluded.currency,
    quantity = excluded.quantity,
    availability_status = excluded.availability_status,
    updated_at = excluded.updated_at;

DROP VIEW IF EXISTS catalog_availability;

-- Consumer-friendly projection with formatted price and effective availability.
-- A stocked item is still unavailable when its store is not open.
CREATE VIEW catalog_availability AS
SELECT
    s.id AS store_id,
    s.name AS store_name,
    s.city,
    s.status AS store_status,
    p.id AS product_id,
    p.sku,
    p.name AS product_name,
    p.brand,
    p.category,
    p.unit_label,
    o.price_cents,
    o.currency,
    ROUND(o.price_cents / 100.0, 2) AS price,
    printf('%.2f %s', o.price_cents / 100.0, o.currency) AS price_display,
    o.quantity,
    o.availability_status AS inventory_status,
    CASE
        WHEN s.status <> 'open' THEN 'store_unavailable'
        ELSE o.availability_status
    END AS effective_status,
    CASE
        WHEN s.status = 'open' AND o.is_available = 1 THEN 1
        ELSE 0
    END AS is_available,
    o.updated_at
FROM catalog_offers AS o
JOIN catalog_stores AS s ON s.id = o.store_id
JOIN catalog_products AS p ON p.id = o.product_id;

COMMIT;
