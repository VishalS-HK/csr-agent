"""Seed synthetic customer records for one fictional electronics store (INR).

Usage (from the repo root, after `python scripts/migrate.py`):

    python scripts/seed_data.py           # refuses if app tables already have data
    python scripts/seed_data.py --reset   # empties all app tables, then seeds

Every row has a fixed id so tests and demos can refer to it. Dates are relative
to now, so "delivered 12 days ago" stays true whenever you seed. Everything is
inserted in one transaction: all of it or none of it.

Cases (doc section in brackets):
  1  Headphones returned, received, inspection passed, no refund yet  [§1, §9, Demo A]
  2  Return requested, not received yet                                [§8 RETURN_NOT_RECEIVED]
  3  Return received, inspection failed                                [Demo B]
  4  Order shipped, not delivered yet                                  [§3A]
  5  Order shipped long ago, still not delivered (shipping delay)      [§9 shipping delays]
  6  Item delivered damaged                                            [§3C]
  7  Order already fully refunded                                      [§1 step 4]
  8  Order belonging to another customer                               [§14]
  9  Ticket with no order attached                                     [§14 missing order info]
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402

# Every app table except schema_migrations, which belongs to migrate.py.
APP_TABLES = [
    "audit_events",
    "refund_operations",
    "approvals",
    "action_proposals",
    "workflow_runs",
    "tickets",
    "returns",
    "order_items",
    "orders",
    "products",
    "customers",
    "policy_chunks",
    "policy_documents",
]

NOW = datetime.now(timezone.utc)


def days_ago(n: int) -> datetime:
    return NOW - timedelta(days=n)


# Fixed ids. First digit = table: 1 customer, 2 product, 3 order,
# 4 order item, 5 return, 6 ticket. Last digits = case number.
def _id(table: int, n: int) -> str:
    return f"{table}0000000-0000-0000-0000-{n:012d}"


ASHA, RAHUL = _id(1, 1), _id(1, 2)

CUSTOMERS = [
    # (id, name, email). external_auth_subject is linked to Supabase Auth in PR 4.
    (ASHA, "Asha Verma", "asha@example.com"),
    (RAHUL, "Rahul Mehta", "rahul@example.com"),
]

PRODUCTS = [
    # (id, name, category)
    (_id(2, 1), "Wireless Headphones", "audio"),
    (_id(2, 2), "Bluetooth Speaker", "audio"),
    (_id(2, 3), "Smartwatch", "wearables"),
    (_id(2, 4), "Power Bank 20000mAh", "accessories"),
    (_id(2, 5), "14-inch Laptop", "computers"),
    (_id(2, 6), "Smartphone", "mobiles"),
    (_id(2, 7), "Wireless Earbuds", "audio"),
    (_id(2, 8), "10-inch Tablet", "tablets"),
]

ORDERS = [
    # (case, customer, product, status, paid paise, refunded paise, placed, delivered)
    (1, ASHA, 1, "delivered", 249900, 0, days_ago(16), days_ago(12)),
    (2, ASHA, 2, "delivered", 399900, 0, days_ago(9), days_ago(6)),
    (3, ASHA, 3, "delivered", 599900, 0, days_ago(19), days_ago(15)),
    (4, ASHA, 4, "shipped", 149900, 0, days_ago(3), None),
    (5, ASHA, 5, "shipped", 5499000, 0, days_ago(14), None),
    (6, ASHA, 6, "delivered", 1899900, 0, days_ago(4), days_ago(1)),
    (7, ASHA, 7, "delivered", 199900, 199900, days_ago(25), days_ago(20)),
    (8, RAHUL, 8, "delivered", 2199900, 0, days_ago(7), days_ago(4)),
]

RETURNS = [
    # (case, status, received_at, inspection_status)
    (1, "received", days_ago(2), "passed"),
    (2, "in_transit", None, "not_inspected"),
    (3, "received", days_ago(5), "failed"),
    (7, "received", days_ago(14), "passed"),
]

TICKETS = [
    # (case, order case or None, category, summary)
    (1, 1, "refund_request",
     "I returned my headphones last week, but I still haven't received my refund."),
    (2, 2, "refund_request",
     "I sent my speaker back a few days ago. When will I get my money?"),
    (3, 3, "refund_request",
     "I returned my smartwatch. Please refund me."),
    (4, 4, "order_status",
     "Where is my power bank? It was shipped a few days ago."),
    (5, 5, "order_status",
     "My laptop was shipped two weeks ago and still hasn't arrived."),
    (6, 6, "damaged_item",
     "My new phone arrived yesterday with a cracked screen."),
    (7, 7, "refund_request",
     "I want a refund for my earbuds."),
    (9, None, "refund_request",
     "I want a refund for something I bought last month."),
]


def seed(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "insert into app.customers (id, name, email) values (%s, %s, %s)",
            CUSTOMERS,
        )
        cur.executemany(
            "insert into app.products (id, name, category) values (%s, %s, %s)",
            PRODUCTS,
        )
        cur.executemany(
            """insert into app.orders (id, customer_id, status, paid_amount_minor,
                   refunded_amount_minor, placed_at, delivered_at)
               values (%s, %s, %s, %s, %s, %s, %s)""",
            [(_id(3, c), cust, st, paid, ref, placed, deliv)
             for c, cust, _, st, paid, ref, placed, deliv in ORDERS],
        )
        cur.executemany(
            """insert into app.order_items (id, order_id, product_id, quantity, paid_amount_minor)
               values (%s, %s, %s, 1, %s)""",
            [(_id(4, c), _id(3, c), _id(2, prod), paid)
             for c, _, prod, _, paid, *_ in ORDERS],
        )
        cur.executemany(
            """insert into app.returns (id, order_id, status, received_at, inspection_status)
               values (%s, %s, %s, %s, %s)""",
            [(_id(5, c), _id(3, c), st, recv, insp) for c, st, recv, insp in RETURNS],
        )
        cur.executemany(
            """insert into app.tickets (id, customer_id, order_id, category, summary)
               values (%s, %s, %s, %s, %s)""",
            [(_id(6, c), ASHA, _id(3, o) if o else None, cat, summary)
             for c, o, cat, summary in TICKETS],
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true",
                        help="empty every app table (except schema_migrations) before seeding")
    args = parser.parse_args()

    settings = Settings(_env_file=ROOT / ".env")
    with psycopg.connect(settings.database_url.get_secret_value()) as conn:
        # One transaction: psycopg commits when the `with` block exits cleanly
        # and rolls back if anything raises.
        if args.reset:
            conn.execute("truncate " + ", ".join(f"app.{t}" for t in APP_TABLES))
            print("Emptied all app tables.")
        else:
            non_empty = [
                t for t in APP_TABLES
                if conn.execute(f"select exists (select 1 from app.{t})").fetchone()[0]
            ]
            if non_empty:
                print(
                    f"ERROR  These tables already have data: {', '.join(non_empty)}.\n"
                    "       Run with --reset to empty them and seed again.",
                    file=sys.stderr,
                )
                return 1

        seed(conn)

    print(
        f"Seeded {len(CUSTOMERS)} customers, {len(PRODUCTS)} products, {len(ORDERS)} orders, "
        f"{len(RETURNS)} returns, {len(TICKETS)} tickets."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
