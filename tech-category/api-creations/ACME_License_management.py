#!/usr/bin/env python3
"""
ACME License Audit Script
--------------------------------
This script will take all active users from the ACME organization, checks their
last active date via the ACME Admin API, and SUSPENDS ACCESS for any user
who has been inactive for more than 60 days. It does NOT deactivate their account.

Suspension uses the org directory suspend-access endpoint. This revokes the
user's access to the organization's products WITHOUT deactivating their account
or removing them from any groups, and is reversible via user management page.
It is a lighter action than fully deactivating the account, while still effectively
restricting access and saving the license cost.
Another reason for SUSPEND versus DEACTIVATE is because you cannot deactivate accounts 
that are billing admins. So, instead of getting this error every time we run the script,
suspending their account successfully achieves the goal that we aimed for and makes it
easier to reverse the suspension versus a deactivation should the user need access again.

The ACME organization charges per user per month. If a user has been inactive on
their account for 60 days, then we assume they no longer need a license and it
can be safely reclaimed to reduce the usage cost.
-mykonos-sky

Requirements:
    pip install requests python-dotenv

Environment variables (set in a .env file or your shell):
    ACME_ORG_ID      - Your ACME organization ID
    ACME_API_KEY     - ACME Admin API key (from admin.ACME.com)

Usage:
    python acme_license_audit.py              # Dry run (no changes made)
    python acme_license_audit.py --execute    # Actually suspend users
"""

import argparse
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Configuration ──────────────────────────────────────────────────────────────

ORG_ID      = os.getenv("ACME_ORG_ID")
API_KEY     = os.getenv("ACME_API_KEY")
INACTIVITY_DAYS = 60

# Service accounts used for integrations with ACME. These are NEVER
# deactivated by this script, regardless of activity, since they may not show
# interactive sign-ins but are essential for integrations and existing workflows.
PROTECTED_EMAILS = {
    "example1@organization.com",
    "example2@organization.com",
}

BASE_URL    = "https://api.acme.com"
HEADERS     = {
    "Authorization": f"Bearer {API_KEY}",
    "Accept":        "application/json",
    "Content-Type":  "application/json",
}

# ── Helpers ────────────────────────────────────────────────────────────────────
# This particular API key has a rate limit of 100 requests per minute.
# This function wraps the requests library to handle rate limiting 
# by retrying on HTTP 429 responses with exponential back-off.
def _request(method: str, url: str, **kwargs) -> requests.Response:
    resp = requests.request(method, url, headers=HEADERS, **kwargs)
    for attempt in range(4):
        if resp.status_code != 429:
            return resp
        retry_after = int(resp.headers.get("Retry-After", min(2 ** attempt, 60)))
        print(f"[WARN] Rate limited (429). Retrying in {retry_after}s …", file=sys.stderr)
        time.sleep(retry_after)
        resp = requests.request(method, url, headers=HEADERS, **kwargs)
    return resp

"""
Return the cursor token from a links.next value.
Handles both bare cursor strings (POST search endpoint) and full URLs
(GET endpoints embed the cursor as ?cursor=...).
"""
def _extract_cursor(next_link: str | None) -> str | None:
    if not next_link:
        return None
    parsed = urllib.parse.urlparse(next_link)
    if parsed.scheme:  # full URL — pull the cursor query param
        qs = urllib.parse.parse_qs(parsed.query)
        return qs.get("cursor", [None])[0]
    return next_link  # bare token

"""
Return all active, managed (ACME) users in the org.
Uses the org user-search endpoint, which (unlike the bare GET .../users
endpoint) actually returns the org's managed ACME accounts. PRODUCT_LAST_ACCESS
is expanded inline so we don't need a separate API call per user.
"""
def get_active_users(debug: bool = False) -> list[dict]:
    url    = f"{BASE_URL}/admin/v1/orgs/{ORG_ID}/users/search"
    users  = []
    cursor = None
    page   = 0

    while True:
        payload = {
            "limit":        1000,
            "expand":       ["NAME", "EMAIL", "PRODUCT_LAST_ACCESS"],
            "accountTypes": ["acme"],   # skip 'app' and 'customer' accounts
        }
        if cursor:
            payload["cursor"] = cursor

        resp = _request("POST", url, json=payload)
        resp.raise_for_status()
        body  = resp.json()
        batch = body.get("data", [])
        users.extend(batch)
        page += 1

        if debug:
            print(f"[DEBUG] page {page}: +{len(batch)} user(s) (running total {len(users)})")

        cursor = _extract_cursor(body.get("links", {}).get("next"))
        if not cursor:
            break

    if debug:
        print(f"\n[DEBUG] Raw user count (before status filter): {len(users)}")
        if users:
            print(f"[DEBUG] Sample user keys: {list(users[0].keys())}")
            print(f"[DEBUG] Sample user accountStatus: {users[0].get('accountStatus')!r}")
        else:
            print("[DEBUG] No users returned at all — check ORG_ID and API_KEY in your .env")

    return [u for u in users if u.get("accountStatus") == "active"]

"""Parse an ACME timestamp (nanosecond precision + 'Z') into a datetime."""
# fromisoformat only accepts up to microsecond precision, so trim extra digits.
def _parse_ts(raw: str) -> datetime:
    raw = re.sub(r"(\.\d{6})\d+", r"\1", raw.strip())
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))

"""
Most recent last-active timestamp across all products for a user.
Reads the inline 'productLastAccess' data from the search response.
Returns a timezone-aware datetime, or None if no activity is recorded.
"""
def get_user_last_active(user: dict) -> datetime | None:
    parsed = [
        _parse_ts(entry["lastActiveTimestamp"])
        for entry in user.get("productLastAccess", [])
        if entry.get("lastActiveTimestamp")
    ]
    return max(parsed) if parsed else None

"""
Return the age of the account in days, or None if creation date is unavailable.
Reads 'createdAt' from the user object (returned by the search API).
"""
def account_age_days(user: dict) -> int | None:
    raw = user.get("createdAt")
    if not raw:
        return None
    try:
        return (datetime.now(tz=timezone.utc) - _parse_ts(raw)).days
    except (ValueError, TypeError):
        return None

"""
Returns (ok, detail): detail holds the error reason when ok is False.
"""
# Surface the real reason. Possible ones:
#   • HTTP 403 — account isn't *managed* (email domain not verified+claimed).
#   • HTTP 409 HAS_ACTIVE_ENTITLEMENT — user is the last billing admin of a
#     transaction account with active entitlements; must be resolved in the
#     admin console (add another billing admin / remove entitlements) first.
def suspend_user(account_id: str) -> tuple[bool, str]:
    url  = f"{BASE_URL}/admin/v1/orgs/{ORG_ID}/directory/users/{account_id}/suspend-access"
    resp = _request("POST", url)
    if resp.status_code in (200, 204):
        return True, ""
    try:
        body = resp.json()
    except ValueError:
        body = None

    if isinstance(body, dict):
        codes = [c.get("code") for c in body.get("errorCodes", []) if c.get("code")]
        detail = body.get("message") or body.get("context") or body.get("errorDetail") or resp.text
        if codes:
            detail = f"{detail} [{', '.join(codes)}]"
    else:
        detail = resp.text
    return False, f"HTTP {resp.status_code}: {detail}".strip()


def fmt_date(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d") if dt else "Never / Unknown"


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ACME License Audit")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually deactivate inactive users (default is dry-run)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print raw API response info to diagnose issues",
    )
    parser.add_argument(
        "--only",
        metavar="EMAIL",
        help="Restrict the run to a single user (by email) — ideal for a safe test",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Suspend at most N users (applied after the inactivity filter)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation (required for automated/non-interactive runs)",
    )
    args = parser.parse_args()

    # ── Validate env vars ──────────────────────────────────────────────────────
    missing = [v for v in ("ACME_ORG_ID", "ACME_API_KEY") if not os.getenv(v)]
    if missing:
        print(f"[ERROR] Missing environment variable(s): {', '.join(missing)}")
        sys.exit(1)

    mode = "EXECUTE" if args.execute else "DRY RUN"
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=INACTIVITY_DAYS)
# Calculates and prints the last inactivity cutoff date based on the configured inactivity threshold.
    print("=" * 60)
    print(f"  ACME License Audit  |  Mode: {mode}")
    print(f"  Action on inactive       : SUSPEND PRODUCT ACCESS (reversible)")
    print(f"  Inactivity threshold     : {INACTIVITY_DAYS} days")
    print(f"  Cutoff date              : {cutoff.strftime('%Y-%m-%d')}")
    print("=" * 60)
    print("  ⚠  Suspends product access only — keeps the account & group memberships.")
    print("     Reversible via the restore-access endpoint.")

    # ── Fetch users ────────────────────────────────────────────────────────────
    print("\n[1/3] Fetching active managed users …")
    try:
        users = get_active_users(debug=args.debug)
    except requests.HTTPError as exc:
        print(f"[ERROR] Could not fetch users: {exc}")
        sys.exit(1)

    print(f"      Found {len(users)} active user(s).")

    if args.only:
        target = args.only.strip().lower()
        users = [u for u in users if (u.get("email") or "").lower() == target]
        if not users:
            print(f"[ERROR] No active user found with email: {args.only}")
            sys.exit(1)
        print(f"      --only filter: restricted to {len(users)} user(s) matching {args.only}")

    # ── Check activity ─────────────────────────────────────────────────────────
    print("\n[2/3] Checking last-active dates …")

    to_deactivate: list[dict] = []
    to_keep:       list[dict] = []
    no_data:       list[dict] = []

    for i, user in enumerate(users, start=1):
        account_id   = user["accountId"]
        display_name = user.get("name", account_id)
        email        = user.get("email", "—")

        last_active = get_user_last_active(user)

        print(f"  [{i:>4}/{len(users)}] {display_name} <{email}>  |  Last active: {fmt_date(last_active)}", end="")
# Checks to see if user is protected emails.
        if (email or "").lower() in PROTECTED_EMAILS:
            print("  → PROTECTED service account (never suspended)")
            to_keep.append({**user, "last_active": last_active})
            continue

        if last_active is None:
            age = account_age_days(user)
            no_data.append({**user, "last_active": None})
            if age is None:
                # Can't determine account age — skip rather than risk suspending a new account.
                print("  → NO DATA, age unknown (skipping)")
            elif age >= INACTIVITY_DAYS:
                print(f"  → NO DATA, account {age}d old (never logged in — will suspend)")
                to_deactivate.append({**user, "last_active": None})
            else:
                print(f"  → NO DATA, account {age}d old (new account — keeping)")
        elif last_active < cutoff:
            days_inactive = (datetime.now(tz=timezone.utc) - last_active).days
            print(f"  → INACTIVE ({days_inactive}d)")
            to_deactivate.append({**user, "last_active": last_active})
        else:
            print("  → ACTIVE")
            to_keep.append({**user, "last_active": last_active})

    if args.limit is not None and len(to_deactivate) > args.limit:
        skipped = len(to_deactivate) - args.limit
        print(f"\n  [!] --limit: capping suspension list from {len(to_deactivate)} to {args.limit} ({skipped} user(s) will NOT be processed this run).")
        to_deactivate = to_deactivate[:args.limit]

    # ── Summary ────────────────────────────────────────────────────────────────
    print("\n[3/3] Summary")
    print(f"  Active (keeping)    : {len(to_keep)}")
    print(f"  Inactive (action)   : {len(to_deactivate)}  ({len(no_data)} with no activity data)")

    if not to_deactivate:
        print("\n  Nothing to do — all users are active. ✓")
        return

    print("\n  Users to be suspended:")
    for u in to_deactivate:
        print(f"    • {u.get('name', u['accountId'])} <{u.get('email', '—')}>  last active: {fmt_date(u['last_active'])}")

    # ── Act ────────────────────────────────────────────────────────────────────
    if not args.execute:
        print(
            "\n  ⚠  DRY RUN — no changes made.\n"
            "     Re-run with --execute to suspend the users above."
        )
        return

    count = len(to_deactivate)
# For dry runs, it checks in with admin running script to suspend found users that are inactive or have no activity data.
    print(
        f"\n  ⚠  About to SUSPEND PRODUCT ACCESS for {count} account(s)."
        "\n     Keeps the account & groups; reversible via restore-access."
    )

    # Confirmation. Interactive runs require a typed phrase; automated runs must
    # pass --yes (otherwise we refuse rather than hang on a missing TTY).
    if args.yes:
        print("  --yes supplied — skipping interactive confirmation.")
    elif not sys.stdin.isatty():
        print(
            "  ✗ ABORTED: non-interactive run without --yes."
            "\n     Add --yes to authorize suspensions in automated/cron runs."
        )
        sys.exit(1)
    else:
        confirm = input(f'  Type "SUSPEND {count}" to proceed: ').strip()
        if confirm != f"SUSPEND {count}":
            print("  Aborted — no changes made.")
            return

    print("\n  Suspending users …")
    success = 0
    failed  = 0
    blocked = 0

    for u in to_deactivate:
        account_id   = u["accountId"]
        display_name = u.get("name", account_id)
        ok, detail = suspend_user(account_id)
        if ok:
            print(f"    ✓ Suspended: {display_name}")
            success += 1
        elif "HAS_ACTIVE_ENTITLEMENT" in detail:
            # Expected, not a script error — resolve in admin console first.
            print(f"    ⚠ Skipped:   {display_name}  →  last billing admin; fix in admin console (add another billing admin / remove entitlements)")
            blocked += 1
        else:
            print(f"    ✗ Failed:    {display_name}  →  {detail}")
            failed += 1
        time.sleep(0.3)

    print(f"\n  Done. Suspended: {success}  |  Blocked (billing admin): {blocked}  |  Failed: {failed}")


if __name__ == "__main__":
    main()
