"""
test_auth.py
Smoke test for auth.py: password policy, pbkdf2 hash/verify roundtrip,
company registration (incl. slug collision + duplicate-email handling) and
login.

Creates its own throwaway companies and deletes them afterwards, even on
failure.

Usage: python3 test_auth.py
"""

import sys
from pathlib import Path

import auth
import db

TEST_COMPANY_NAME = "__test_auth_smoke__"


def fail(msg):
    print(f"FAIL: {msg}")
    sys.exit(1)


def cleanup(slug):
    conn = db.get_directory_conn()
    conn.execute(
        "DELETE FROM users WHERE company_id IN (SELECT id FROM companies WHERE slug = ?)", (slug,)
    )
    conn.execute("DELETE FROM companies WHERE slug = ?", (slug,))
    conn.commit()
    conn.close()
    path = db.tenant_db_path(slug)
    if path.exists():
        path.unlink()
    for suffix in ("-wal", "-shm"):
        extra = Path(str(path) + suffix)
        if extra.exists():
            extra.unlink()


def main():
    db.init_directory_db()

    # ── Password policy ──────────────────────────────────────────────────
    if auth.password_problem("short1") is None:
        fail("password_problem should reject passwords under 8 characters")
    print("OK  password_problem rejects too-short passwords")

    if auth.password_problem("password1") is None:
        fail("password_problem should reject common passwords")
    print("OK  password_problem rejects common passwords")

    if auth.password_problem("john12345", email="john@company.se") is None:
        fail("password_problem should reject a password containing the email's local part")
    print("OK  password_problem rejects passwords containing the email local part")

    if auth.password_problem("SakertLosen2026") is not None:
        fail("password_problem incorrectly rejected an acceptable password")
    print("OK  password_problem accepts a reasonable password")

    # ── Hash/verify roundtrip ─────────────────────────────────────────────
    h, salt = auth.hash_new_password("SakertLosen2026")
    if not auth.verify_password("SakertLosen2026", salt, h):
        fail("verify_password failed to verify the password it just hashed")
    if auth.verify_password("WrongPassword1", salt, h):
        fail("verify_password incorrectly accepted a wrong password")
    print("OK  hash_new_password / verify_password roundtrip")

    # ── Registration + slug collision ────────────────────────────────────
    user1, err1 = auth.register_company(TEST_COMPANY_NAME, "a@authsmoke.local", "SakertLosen2026")
    if err1:
        fail(f"register_company (1st) failed: {err1}")
    user2, err2 = auth.register_company(TEST_COMPANY_NAME, "b@authsmoke.local", "SakertLosen2026")
    if err2:
        fail(f"register_company (2nd, same name) failed: {err2}")
    if user1.company_slug == user2.company_slug:
        fail("slug collision was not resolved: two companies got the same slug")
    if not db.tenant_exists(user1.company_slug) or not db.tenant_exists(user2.company_slug):
        fail("tenant db file was not created for one of the registered companies")
    print(f"OK  register_company resolves slug collisions ({user1.company_slug} vs {user2.company_slug})")

    _, dup_err = auth.register_company("Different Name AB", "a@authsmoke.local", "SakertLosen2026")
    if dup_err is None:
        fail("register_company should reject a duplicate email even with a different company name")
    print("OK  register_company rejects a duplicate email")

    # ── Login ─────────────────────────────────────────────────────────────
    logged_in, login_err = auth.login("a@authsmoke.local", "SakertLosen2026")
    if login_err:
        fail(f"login with correct credentials failed: {login_err}")
    if logged_in.company_slug != user1.company_slug:
        fail("login returned the wrong company")
    print("OK  login succeeds with correct credentials")

    _, wrong_err = auth.login("a@authsmoke.local", "WrongPassword1")
    if wrong_err is None:
        fail("login should reject an incorrect password")
    print("OK  login rejects incorrect password")

    _, missing_err = auth.login("nobody@authsmoke.local", "SakertLosen2026")
    if missing_err is None:
        fail("login should reject an unknown email")
    print("OK  login rejects unknown email")

    cleanup(user1.company_slug)
    cleanup(user2.company_slug)
    print("\nALL auth.py CHECKS PASSED")


if __name__ == "__main__":
    main()
