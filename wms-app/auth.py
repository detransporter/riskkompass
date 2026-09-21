"""Local auth: no Supabase, no external service. One shared directory.db
holds companies + users; passwords are hashed with stdlib pbkdf2 so the app
has no C-extension dependency to build on the deploy VPS.

password_problem() is ported verbatim from iha-saas/auth.py (pure Python
there too, no Supabase coupling) -- same policy, same wording, so the two
apps never drift on what counts as an acceptable password.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass

import db

# ── Password policy (verbatim from iha-saas/auth.py) ────────────────────────
MIN_PASSWORD_LEN = 8

_COMMON_PASSWORDS = {
    "password", "password1", "password123", "12345678", "123456789",
    "1234567890", "qwertyui", "qwerty123", "iloveyou", "sunshine",
    "admin123", "welcome1", "sommar2024", "sommar2025", "sommar2026",
    "11111111", "00000000", "abc12345", "letmein1", "monkey123",
}


def password_problem(password: str, email: str = "", lang: str = "sv") -> str | None:
    """Return a user-facing problem description, or None if acceptable."""
    if len(password) < MIN_PASSWORD_LEN:
        if lang == "sv":
            return f"Lösenordet måste vara minst {MIN_PASSWORD_LEN} tecken."
        return f"Password must be at least {MIN_PASSWORD_LEN} characters."
    if password.lower() in _COMMON_PASSWORDS:
        if lang == "sv":
            return "Det lösenordet finns på varje angripares gissningslista — välj ett annat."
        return "That password is on every attacker's first-guess list — pick another."
    local_part = (email or "").split("@")[0].lower()
    if local_part and len(local_part) >= 4 and local_part in password.lower():
        if lang == "sv":
            return "Lösenordet får inte innehålla din e-postadress."
        return "Password must not contain your email address."
    return None


# ── Password hashing ─────────────────────────────────────────────────────
_PBKDF2_ITERATIONS = 600_000  # OWASP 2023 recommendation for HMAC-SHA256


def _hash_password(password: str, salt_hex: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), _PBKDF2_ITERATIONS
    ).hex()


def hash_new_password(password: str) -> tuple[str, str]:
    """Returns (password_hash, password_salt), both hex strings."""
    salt_hex = secrets.token_hex(16)
    return _hash_password(password, salt_hex), salt_hex


def verify_password(password: str, salt_hex: str, expected_hash_hex: str) -> bool:
    return secrets.compare_digest(_hash_password(password, salt_hex), expected_hash_hex)


# ── Session data ──────────────────────────────────────────────────────────

@dataclass
class User:
    id: int
    email: str
    role: str
    company_id: int
    company_slug: str
    company_name: str


# ── Registration ──────────────────────────────────────────────────────────

def _unique_slug(conn: sqlite3.Connection, base_slug: str) -> str:
    slug = base_slug
    n = 2
    while conn.execute("SELECT 1 FROM companies WHERE slug = ?", (slug,)).fetchone():
        slug = f"{base_slug}-{n}"
        n += 1
    return slug


def register_company(
    company_name: str, email: str, password: str, lang: str = "sv",
) -> tuple[User | None, str | None]:
    """Create a company + its first admin user + its tenant database.

    Returns (user, error). On error, user is None and nothing was written.
    """
    problem = password_problem(password, email, lang)
    if problem:
        return None, problem

    conn = db.get_directory_conn()
    try:
        if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            if lang == "sv":
                return None, "Det finns redan ett konto med den här e-postadressen."
            return None, "An account with this email already exists."

        slug = _unique_slug(conn, db.slugify(company_name))
        now = db.now_iso()

        cur = conn.execute(
            "INSERT INTO companies (slug, name, created_at) VALUES (?, ?, ?)",
            (slug, company_name.strip(), now),
        )
        company_id = cur.lastrowid

        password_hash, password_salt = hash_new_password(password)
        cur = conn.execute(
            """
            INSERT INTO users (company_id, email, password_hash, password_salt, role, created_at)
            VALUES (?, ?, ?, ?, 'admin', ?)
            """,
            (company_id, email.strip().lower(), password_hash, password_salt, now),
        )
        user_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    db.init_tenant_db(slug)

    return User(
        id=user_id, email=email.strip().lower(), role="admin",
        company_id=company_id, company_slug=slug, company_name=company_name.strip(),
    ), None


# ── Login ─────────────────────────────────────────────────────────────────

def login(email: str, password: str, lang: str = "sv") -> tuple[User | None, str | None]:
    conn = db.get_directory_conn()
    try:
        row = conn.execute(
            """
            SELECT u.id, u.email, u.password_hash, u.password_salt, u.role,
                   c.id AS company_id, c.slug AS company_slug, c.name AS company_name
            FROM users u JOIN companies c ON c.id = u.company_id
            WHERE u.email = ?
            """,
            (email.strip().lower(),),
        ).fetchone()
    finally:
        conn.close()

    if not row or not verify_password(password, row["password_salt"], row["password_hash"]):
        return None, ("Fel e-post eller lösenord." if lang == "sv" else "Incorrect email or password.")

    return User(
        id=row["id"], email=row["email"], role=row["role"],
        company_id=row["company_id"], company_slug=row["company_slug"],
        company_name=row["company_name"],
    ), None
