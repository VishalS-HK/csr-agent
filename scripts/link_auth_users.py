"""Give every seeded customer a Supabase Auth login and link it to their record.

Usage (from the repo root, after `python scripts/seed_data.py`):

    python scripts/link_auth_users.py --password 'some-test-password'

For each row in app.customers it finds the Supabase user with the same email,
creating one (email already confirmed) if none exists, and stores that user's
id in app.customers.external_auth_subject. Safe to run again: existing users
keep their current password, and links are simply rewritten.

Needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env. The service-role key
bypasses all access rules, so it is used here and nowhere in the app.
These are synthetic test customers; don't point this at real users.
"""

import argparse
import sys
from pathlib import Path

import httpx
import psycopg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402

PER_PAGE = 1000


def list_users(client: httpx.Client) -> dict[str, str]:
    """Return {lowercased email: user id} for every Supabase Auth user."""
    users: dict[str, str] = {}
    page = 1
    while True:
        resp = client.get("/admin/users", params={"page": page, "per_page": PER_PAGE})
        resp.raise_for_status()
        batch = resp.json()["users"]
        users.update({u["email"].lower(): u["id"] for u in batch if u.get("email")})
        if len(batch) < PER_PAGE:
            return users
        page += 1


def create_user(client: httpx.Client, email: str, name: str, password: str) -> str:
    resp = client.post(
        "/admin/users",
        json={
            "email": email,
            "password": password,
            "email_confirm": True,  # skip the confirmation email
            "user_metadata": {"name": name},
        },
    )
    resp.raise_for_status()
    return resp.json()["id"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--password", required=True,
                        help="password for newly created logins (at least 6 characters)")
    args = parser.parse_args()
    if len(args.password) < 6:
        parser.error("--password must be at least 6 characters (Supabase's minimum)")

    settings = Settings(_env_file=ROOT / ".env")
    key = settings.supabase_service_role_key.get_secret_value()
    if not key:
        print("ERROR  Set SUPABASE_SERVICE_ROLE_KEY in .env first.", file=sys.stderr)
        return 1

    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    with (
        httpx.Client(base_url=f"{settings.supabase_url}/auth/v1", headers=headers,
                     timeout=15) as client,
        psycopg.connect(settings.database_url.get_secret_value()) as conn,
    ):
        customers = conn.execute(
            "select id, name, email from app.customers order by email"
        ).fetchall()
        if not customers:
            print("ERROR  app.customers is empty. Run scripts/seed_data.py first.",
                  file=sys.stderr)
            return 1

        try:
            existing = list_users(client)
            for customer_id, name, email in customers:
                user_id = existing.get(email.lower())
                if user_id:
                    print(f"exists  {email}  (password unchanged)")
                else:
                    user_id = create_user(client, email, name, args.password)
                    print(f"created {email}")
                conn.execute(
                    "update app.customers set external_auth_subject = %s where id = %s",
                    (user_id, customer_id),
                )
        except httpx.HTTPStatusError as exc:
            # Undo this run's links. Any logins already created stay in
            # Supabase; the next run finds and links them.
            conn.rollback()
            print(f"ERROR  Supabase returned {exc.response.status_code}: "
                  f"{exc.response.text}", file=sys.stderr)
            return 1

    print(f"Linked {len(customers)} customers to Supabase Auth.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
