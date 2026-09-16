-- =====================================================================
-- WMS-app -- directory schema (the ONE shared database)
-- =====================================================================
--
-- This file holds ONLY identity: which companies exist, which users belong
-- to them, and which tenant database file a logged-in user is allowed to
-- open. It never holds operational or inventory data -- that lives in
-- data/tenants/<company_slug>.db, one file per company, kept physically
-- separate so a query bug here can never leak one company's stock/orders to
-- another. See CLAUDE.md "Flerkundsmodell" for the full reasoning.
--
-- Written in the SQLite/PostgreSQL intersection (CHECK instead of enums,
-- ISO-8601 TEXT dates, INTEGER 0/1 for booleans) so a future move to
-- Postgres, if a tenant ever outgrows SQLite's single-writer model, does not
-- require a schema rewrite.
-- =====================================================================

CREATE TABLE IF NOT EXISTS companies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT NOT NULL UNIQUE,   -- filesystem-safe key -> tenants/<slug>.db
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL           -- ISO-8601
);

CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id     INTEGER NOT NULL REFERENCES companies(id),
    email          TEXT NOT NULL UNIQUE,
    password_hash  TEXT NOT NULL,       -- pbkdf2_hmac hex digest
    password_salt  TEXT NOT NULL,       -- hex, unique per user
    role           TEXT NOT NULL DEFAULT 'admin'
                       CHECK (role IN ('admin', 'operator')),
    created_at     TEXT NOT NULL        -- ISO-8601
);

CREATE INDEX IF NOT EXISTS ix_users_company ON users (company_id);
