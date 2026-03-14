#!/usr/bin/env python3
"""Skool Sales Tracker — log every sale, renewal, and payout, then reconcile."""

import csv
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
TRANSACTIONS_FILE = DATA_DIR / "transactions.csv"
PAYOUTS_FILE = DATA_DIR / "payouts.csv"

STRIPE_RATE = 0.029     # Stripe takes 2.9%
STRIPE_FIXED = 0.30     # + $0.30 per transaction
DEFAULT_CURRENCY = "USD"
CURRENCY_SYMBOL = {"GBP": "\u00a3", "USD": "$", "EUR": "\u20ac"}

TRANSACTION_FIELDS = [
    "id", "date", "member_name", "type", "amount", "skool_fee",
    "net_amount", "currency", "status", "payout_id", "notes"
]
PAYOUT_FIELDS = [
    "id", "date", "amount", "currency", "matched_total", "unmatched", "notes"
]


def sym(currency=None):
    return CURRENCY_SYMBOL.get(currency or DEFAULT_CURRENCY, "$")


def calc_fee(amount):
    fee = round(amount * STRIPE_RATE + STRIPE_FIXED, 2)
    net = round(amount - fee, 2)
    return fee, net


def ensure_files():
    DATA_DIR.mkdir(exist_ok=True)
    if not TRANSACTIONS_FILE.exists():
        with open(TRANSACTIONS_FILE, "w", newline="") as f:
            csv.DictWriter(f, TRANSACTION_FIELDS).writeheader()
    if not PAYOUTS_FILE.exists():
        with open(PAYOUTS_FILE, "w", newline="") as f:
            csv.DictWriter(f, PAYOUT_FIELDS).writeheader()


def next_id(filepath, prefix):
    rows = read_csv(filepath)
    if not rows:
        return f"{prefix}001"
    last = max(int(r["id"].replace(prefix, "")) for r in rows)
    return f"{prefix}{last + 1:03d}"


def read_csv(filepath):
    if not filepath.exists():
        return []
    with open(filepath, newline="") as f:
        return list(csv.DictReader(f))


def append_row(filepath, fields, row):
    with open(filepath, "a", newline="") as f:
        w = csv.DictWriter(f, fields)
        w.writerow(row)


def write_all(filepath, fields, rows):
    with open(filepath, "w", newline="") as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        w.writerows(rows)


def make_transaction(name, amount_str, txn_type, date=None, notes=""):
    amount = float(amount_str)
    fee, net = calc_fee(amount)
    return {
        "id": next_id(TRANSACTIONS_FILE, "T"),
        "date": date or datetime.now().strftime("%Y-%m-%d"),
        "member_name": name,
        "type": txn_type,
        "amount": str(amount),
        "skool_fee": str(fee),
        "net_amount": str(net),
        "currency": DEFAULT_CURRENCY,
        "status": "pending",
        "payout_id": "",
        "notes": notes,
    }


# ── Commands ─────────────────────────────────────────────────────────

def cmd_sale(args):
    """Log a new member sale: sale <name> <amount> [date] [notes]"""
    if len(args) < 2:
        print("Usage: sale <member_name> <amount> [YYYY-MM-DD] [notes]")
        return
    name, amount = args[0], args[1]
    date = args[2] if len(args) > 2 else None
    notes = " ".join(args[3:]) if len(args) > 3 else ""
    ensure_files()
    row = make_transaction(name, amount, "new", date, notes)
    append_row(TRANSACTIONS_FILE, TRANSACTION_FIELDS, row)
    s = sym()
    print(f"Logged new sale: {name} {s}{amount} on {row['date']} [{row['id']}]")
    print(f"  Processing fee: {s}{row['skool_fee']}  |  Net: {s}{row['net_amount']}")


def cmd_renewal(args):
    """Log a renewal: renewal <name> <amount> [date] [notes]"""
    if len(args) < 2:
        print("Usage: renewal <member_name> <amount> [YYYY-MM-DD] [notes]")
        return
    name, amount = args[0], args[1]
    date = args[2] if len(args) > 2 else None
    notes = " ".join(args[3:]) if len(args) > 3 else ""
    ensure_files()
    row = make_transaction(name, amount, "renewal", date, notes)
    append_row(TRANSACTIONS_FILE, TRANSACTION_FIELDS, row)
    s = sym()
    print(f"Logged renewal: {name} {s}{amount} on {row['date']} [{row['id']}]")
    print(f"  Processing fee: {s}{row['skool_fee']}  |  Net: {s}{row['net_amount']}")


def cmd_bulk(args):
    """Bulk-add multiple transactions interactively."""
    ensure_files()
    print("Bulk entry mode. Type each line as: <new|renewal> <name> <amount> [YYYY-MM-DD]")
    print("Empty line to finish.\n")
    s = sym()
    count = 0
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            break
        parts = line.split()
        if len(parts) < 3:
            print("  Need at least: <new|renewal> <name> <amount>")
            continue
        txn_type = parts[0].lower()
        if txn_type not in ("new", "renewal"):
            print("  First word must be 'new' or 'renewal'")
            continue
        name, amount = parts[1], parts[2]
        date = parts[3] if len(parts) > 3 else None
        row = make_transaction(name, amount, txn_type, date)
        append_row(TRANSACTIONS_FILE, TRANSACTION_FIELDS, row)
        count += 1
        print(f"  {txn_type}: {name} {s}{amount} (net {s}{row['net_amount']}) on {row['date']} [{row['id']}]")
    print(f"\nAdded {count} transactions.")


def cmd_payout(args):
    """Log a payout: payout <amount> [date] [notes]"""
    if len(args) < 1:
        print("Usage: payout <amount> [YYYY-MM-DD] [notes]")
        return
    amount = float(args[0])
    date = args[1] if len(args) > 1 else datetime.now().strftime("%Y-%m-%d")
    notes = " ".join(args[2:]) if len(args) > 2 else ""
    ensure_files()
    s = sym()

    # Auto-match: find pending transactions by net amount (what you actually receive)
    txns = read_csv(TRANSACTIONS_FILE)
    pending = [t for t in txns if t["status"] == "pending"]
    pending.sort(key=lambda t: t["date"])

    payout_id = next_id(PAYOUTS_FILE, "P")
    matched_total = 0.0
    matched_ids = []

    for t in pending:
        net = float(t.get("net_amount", t["amount"]))
        if matched_total + net <= amount + 0.01:
            t["status"] = "paid_out"
            t["payout_id"] = payout_id
            matched_total += net
            matched_ids.append(t["id"])

    unmatched = round(amount - matched_total, 2)
    payout_row = {
        "id": payout_id,
        "date": date,
        "amount": str(amount),
        "currency": DEFAULT_CURRENCY,
        "matched_total": str(round(matched_total, 2)),
        "unmatched": str(unmatched),
        "notes": notes,
    }
    append_row(PAYOUTS_FILE, PAYOUT_FIELDS, payout_row)
    write_all(TRANSACTIONS_FILE, TRANSACTION_FIELDS, txns)

    print(f"Logged payout: {s}{amount} on {date} [{payout_id}]")
    print(f"  Matched {len(matched_ids)} transactions totaling {s}{matched_total:.2f} (net after fees)")
    if matched_ids:
        print(f"  IDs: {', '.join(matched_ids)}")
    if abs(unmatched) > 0.01:
        print(f"  Unmatched: {s}{unmatched:.2f} (timing differences or missing transactions)")


def cmd_status(args):
    """Show current status: pending sales, upcoming payout estimate."""
    ensure_files()
    txns = read_csv(TRANSACTIONS_FILE)
    payouts = read_csv(PAYOUTS_FILE)
    s = sym()

    pending = [t for t in txns if t["status"] == "pending"]
    paid_out = [t for t in txns if t["status"] == "paid_out"]

    gross_all = sum(float(t["amount"]) for t in txns)
    fees_all = sum(float(t.get("skool_fee", 0)) for t in txns)
    net_all = sum(float(t.get("net_amount", t["amount"])) for t in txns)
    net_pending = sum(float(t.get("net_amount", t["amount"])) for t in pending)
    net_paid = sum(float(t.get("net_amount", t["amount"])) for t in paid_out)

    new_count = len([t for t in txns if t["type"] == "new"])
    renewal_count = len([t for t in txns if t["type"] == "renewal"])

    print("=== SKOOL SALES STATUS ===\n")
    print(f"Total transactions:  {len(txns)} ({new_count} new, {renewal_count} renewals)")
    print(f"Gross revenue:       {s}{gross_all:,.2f}")
    print(f"Processing fees:     {s}{fees_all:,.2f}")
    print(f"Net revenue:         {s}{net_all:,.2f}")
    print(f"Paid out:            {s}{net_paid:,.2f} ({len(paid_out)} txns)")
    print(f"Pending:             {s}{net_pending:,.2f} ({len(pending)} txns)")
    print(f"Total payouts:       {len(payouts)}")

    if pending:
        print(f"\n-- Pending Transactions --")
        for t in sorted(pending, key=lambda x: x["date"]):
            net = float(t.get("net_amount", t["amount"]))
            print(f"  {t['id']}  {t['date']}  {t['type']:8s}  {t['member_name']:20s}  {s}{float(t['amount']):>8.2f}  (net {s}{net:>8.2f})")

    # Next Wednesday estimate
    today = datetime.now()
    days_until_wed = (2 - today.weekday()) % 7
    if days_until_wed == 0:
        days_until_wed = 7
    next_wed = today + timedelta(days=days_until_wed)
    settled_cutoff = today - timedelta(days=7)
    likely_settled = [t for t in pending if t["date"] <= settled_cutoff.strftime("%Y-%m-%d")]
    settled_net = sum(float(t.get("net_amount", t["amount"])) for t in likely_settled)

    print(f"\n-- Next Payout (est. {next_wed.strftime('%Y-%m-%d')}) --")
    print(f"  Likely settled (7+ days old):  {s}{settled_net:,.2f} ({len(likely_settled)} txns)")
    print(f"  Still settling (<7 days):      {s}{net_pending - settled_net:,.2f} ({len(pending) - len(likely_settled)} txns)")


def cmd_list(args):
    """List transactions with optional filter: list [all|pending|paid_out|new|renewal]"""
    ensure_files()
    txns = read_csv(TRANSACTIONS_FILE)
    filter_by = args[0] if args else "all"
    s = sym()

    if filter_by == "pending":
        txns = [t for t in txns if t["status"] == "pending"]
    elif filter_by == "paid_out":
        txns = [t for t in txns if t["status"] == "paid_out"]
    elif filter_by == "new":
        txns = [t for t in txns if t["type"] == "new"]
    elif filter_by == "renewal":
        txns = [t for t in txns if t["type"] == "renewal"]

    if not txns:
        print("No transactions found.")
        return

    print(f"{'ID':<6} {'Date':<12} {'Type':<9} {'Member':<20} {'Gross':>8} {'Fee':>7} {'Net':>8} {'Status':<9} {'Payout':<6}")
    print("-" * 95)
    for t in sorted(txns, key=lambda x: x["date"]):
        amt = float(t["amount"])
        fee = float(t.get("skool_fee", 0))
        net = float(t.get("net_amount", t["amount"]))
        print(f"{t['id']:<6} {t['date']:<12} {t['type']:<9} {t['member_name']:<20} {s}{amt:>7.2f} {s}{fee:>6.2f} {s}{net:>7.2f} {t['status']:<9} {t['payout_id']:<6}")


def cmd_payouts(args):
    """List all payouts."""
    ensure_files()
    payouts = read_csv(PAYOUTS_FILE)
    s = sym()
    if not payouts:
        print("No payouts logged yet.")
        return

    print(f"{'ID':<6} {'Date':<12} {'Amount':>10} {'Matched':>10} {'Unmatched':>10} {'Notes'}")
    print("-" * 70)
    for p in payouts:
        print(f"{p['id']:<6} {p['date']:<12} {s}{float(p['amount']):>9.2f} {s}{float(p['matched_total']):>9.2f} {s}{float(p['unmatched']):>9.2f} {p['notes']}")


def cmd_summary(args):
    """Monthly summary report: summary [YYYY-MM]"""
    ensure_files()
    txns = read_csv(TRANSACTIONS_FILE)
    payouts = read_csv(PAYOUTS_FILE)
    s = sym()

    if not txns:
        print("No transactions to summarise.")
        return

    # If month specified, filter to that month; otherwise show all months
    target_month = args[0] if args else None

    # Group transactions by month
    by_month = defaultdict(list)
    for t in txns:
        month = t["date"][:7]  # YYYY-MM
        if target_month and month != target_month:
            continue
        by_month[month].append(t)

    # Group payouts by month
    payouts_by_month = defaultdict(list)
    for p in payouts:
        month = p["date"][:7]
        payouts_by_month[month].append(p)

    if not by_month:
        print(f"No transactions for {target_month}.")
        return

    grand_gross = 0
    grand_fees = 0
    grand_net = 0
    grand_paid = 0

    for month in sorted(by_month.keys()):
        month_txns = by_month[month]
        new = [t for t in month_txns if t["type"] == "new"]
        renewals = [t for t in month_txns if t["type"] == "renewal"]
        gross = sum(float(t["amount"]) for t in month_txns)
        fees = sum(float(t.get("skool_fee", 0)) for t in month_txns)
        net = sum(float(t.get("net_amount", t["amount"])) for t in month_txns)
        month_payouts = payouts_by_month.get(month, [])
        paid = sum(float(p["amount"]) for p in month_payouts)

        grand_gross += gross
        grand_fees += fees
        grand_net += net
        grand_paid += paid

        print(f"=== {month} ===")
        print(f"  New members:    {len(new)}")
        print(f"  Renewals:       {len(renewals)}")
        print(f"  Gross revenue:  {s}{gross:,.2f}")
        print(f"  Processing fees:     {s}{fees:,.2f}")
        print(f"  Net revenue:    {s}{net:,.2f}")
        print(f"  Payouts:        {s}{paid:,.2f} ({len(month_payouts)} payouts)")
        print()

    if len(by_month) > 1:
        print(f"=== TOTAL ===")
        print(f"  Gross: {s}{grand_gross:,.2f}  |  Fees: {s}{grand_fees:,.2f}  |  Net: {s}{grand_net:,.2f}  |  Paid out: {s}{grand_paid:,.2f}")


def cmd_sync(args):
    """Sync members directly from Skool API using auth token."""
    import json
    import re
    import urllib.request
    ensure_files()
    s = sym()

    # Load token from .env
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        print("No .env file found. Create one with SKOOL_AUTH_TOKEN=<token> and SKOOL_GROUP=<group>")
        return
    env = {}
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()

    token = env.get("SKOOL_AUTH_TOKEN")
    group = env.get("SKOOL_GROUP", "luke")
    if not token:
        print("SKOOL_AUTH_TOKEN not found in .env")
        return

    # Fetch members page (contains all data as JSON in __NEXT_DATA__)
    url = f"https://www.skool.com/{group}/-/members"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Cookie": f"auth_token={token}; client_id={env.get('SKOOL_CLIENT_ID', '')}",
    })
    try:
        with urllib.request.urlopen(req) as resp:
            html = resp.read().decode("utf-8")
    except Exception as e:
        print(f"Failed to fetch Skool: {e}")
        return

    # Parse __NEXT_DATA__ JSON
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
    if not match:
        print("Could not find member data in page. Token may have expired.")
        return

    data = json.loads(match.group(1))
    users = data["props"]["pageProps"]["users"]
    total_pages = data["props"]["pageProps"]["totalPages"]

    # Handle pagination if needed
    all_users = list(users)
    for page in range(2, total_pages + 1):
        page_url = f"{url}?p={page}"
        req = urllib.request.Request(page_url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Cookie": f"auth_token={token}; client_id={env.get('SKOOL_CLIENT_ID', '')}",
        })
        with urllib.request.urlopen(req) as resp:
            page_html = resp.read().decode("utf-8")
        page_match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', page_html)
        if page_match:
            page_data = json.loads(page_match.group(1))
            all_users.extend(page_data["props"]["pageProps"]["users"])

    # Process members
    existing = read_csv(TRANSACTIONS_FILE)
    existing_names = {(t["member_name"], t["date"][:10]) for t in existing}

    count = 0
    skipped_free = 0
    skipped_existing = 0

    for u in all_users:
        member = u.get("member", {})
        meta = member.get("metadata", {})
        mmbp_str = meta.get("mmbp", "")

        if not mmbp_str:
            skipped_free += 1
            continue

        mmbp = json.loads(mmbp_str)
        amount_cents = mmbp.get("amount", 0)
        if amount_cents == 0:
            skipped_free += 1
            continue

        amount = amount_cents / 100
        interval = mmbp.get("recurring_interval", "month")
        name = f"{u.get('firstName', '')}_{u.get('lastName', '')}".strip("_")
        joined = member.get("approvedAt", u.get("createdAt", ""))[:10]

        if (name, joined) in existing_names:
            skipped_existing += 1
            continue

        notes = f"{interval}ly"
        row = make_transaction(name, str(amount), "new", joined, notes)
        append_row(TRANSACTIONS_FILE, TRANSACTION_FIELDS, row)
        existing_names.add((name, joined))
        count += 1
        print(f"  {row['id']}  {joined}  {name:25s}  {s}{amount:>7.2f}  (net {s}{row['net_amount']})")

    print(f"\nSynced from Skool: {count} new, {skipped_free} free, {skipped_existing} existing.")
    if count > 0:
        print("Run 'dashboard' to update the visual.")


def cmd_import(args):
    """Import from Skool CSV export: import <path_to_csv>"""
    if not args:
        print("Usage: import <path_to_community_members.csv>")
        return
    filepath = Path(" ".join(args))
    if not filepath.exists():
        print(f"File not found: {filepath}")
        return
    ensure_files()
    s = sym()

    existing = read_csv(TRANSACTIONS_FILE)
    existing_names = {(t["member_name"], t["date"][:10]) for t in existing}

    with open(filepath, newline="") as f:
        reader = csv.DictReader(f)
        count = 0
        skipped_free = 0
        skipped_existing = 0
        for r in reader:
            name = f"{r['FirstName']}_{r['LastName']}".strip("_")
            price_str = r.get("Price", "").replace("$", "").replace(",", "").strip()
            if not price_str or float(price_str) == 0:
                skipped_free += 1
                continue
            date = r["JoinedDate"][:10]
            if (name, date) in existing_names:
                skipped_existing += 1
                continue
            interval = r.get("Recurring Interval", "month")
            notes = f"{interval}ly"
            row = make_transaction(name, price_str, "new", date, notes)
            append_row(TRANSACTIONS_FILE, TRANSACTION_FIELDS, row)
            existing_names.add((name, date))
            count += 1
            print(f"  {row['id']}  {date}  {name:25s}  {s}{price_str:>6}  (net {s}{row['net_amount']})")
    print(f"\nImported {count} paying members. Skipped {skipped_free} free, {skipped_existing} duplicates.")


def load_brand_config():
    """Load branding from .env file."""
    env_path = Path(__file__).parent / ".env"
    env = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return {
        "name": env.get("BRAND_NAME", "My Community"),
        "logo": env.get("BRAND_LOGO", ""),
        "accent": env.get("BRAND_ACCENT", "#3b82f6"),
        "launch_date": env.get("BRAND_LAUNCH_DATE", ""),
        "launch_label": env.get("BRAND_LAUNCH_LABEL", "Launch"),
    }


def cmd_dashboard(args):
    """Generate an HTML dashboard and open it."""
    import json
    import subprocess
    ensure_files()
    txns = read_csv(TRANSACTIONS_FILE)
    payouts = read_csv(PAYOUTS_FILE)
    s = sym()
    brand = load_brand_config()

    txns_json = json.dumps([{
        "id": t["id"], "date": t["date"][:10], "name": t["member_name"].replace("_", " "),
        "type": t["type"], "amount": float(t["amount"]),
        "fee": float(t.get("skool_fee", 0)), "net": float(t.get("net_amount", t["amount"])),
        "status": t["status"], "payout_id": t["payout_id"], "notes": t.get("notes", ""),
        "source": t.get("notes", "").split(" - ")[-1] if " - " in t.get("notes", "") else ""
    } for t in txns])

    payouts_json = json.dumps([{
        "id": p["id"], "date": p["date"][:10], "amount": float(p["amount"]),
        "matched": float(p["matched_total"]), "unmatched": float(p["unmatched"]),
        "notes": p["notes"]
    } for p in payouts])

    brand_json = json.dumps(brand)
    logo_html = f'<img src="{brand["logo"]}" alt="" class="brand-logo">' if brand["logo"] else ""
    launch_btn = f"""<button class="filter-btn" data-filter="launch" onclick="setFilter('launch')">{brand["launch_label"]}</button>""" if brand["launch_date"] else ""

    acc = brand["accent"].lstrip("#")
    acc_r, acc_g, acc_b = int(acc[0:2], 16), int(acc[2:4], 16), int(acc[4:6], 16)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{brand["name"]} &mdash; Revenue Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;1,9..40,400&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

  :root {{
    --bg: #101010; --surface: #181818; --surface-raised: #1f1f1f;
    --border: #2a2a2a; --border-subtle: #222;
    --text: #d4d4d4; --text-secondary: #737373; --text-dim: #525252;
    --positive: #22c55e; --negative: #dc2626; --warning: #ca8a04;
    --accent: {brand["accent"]}; --accent-rgb: {acc_r},{acc_g},{acc_b};
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: var(--bg); color: var(--text);
    font-family: 'DM Sans', sans-serif;
    line-height: 1.5; -webkit-font-smoothing: antialiased;
  }}
  .wrap {{ max-width: 1360px; margin: 0 auto; padding: 40px 32px; }}

  /* ── Header ── */
  header {{
    display: flex; justify-content: space-between; align-items: flex-end;
    margin-bottom: 40px; padding-bottom: 20px;
    border-bottom: 2px solid var(--border);
  }}
  .brand {{ display: flex; align-items: center; gap: 12px; }}
  .brand-logo {{ height: 28px; width: auto; }}
  .brand h1 {{
    font-size: 1.1rem; font-weight: 500; letter-spacing: 0.02em;
    color: var(--text);
  }}
  .brand h1 span {{ color: var(--text-dim); font-weight: 300; }}
  .meta {{ color: var(--text-dim); font-size: 0.72rem; font-family: 'IBM Plex Mono', monospace; letter-spacing: 0.04em; }}
  nav {{ display: flex; gap: 0; }}
  .tab {{
    background: none; border: none; border-bottom: 2px solid transparent;
    color: var(--text-dim); padding: 8px 16px; cursor: pointer;
    font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; font-weight: 500;
    letter-spacing: 0.06em; text-transform: uppercase; transition: all 0.1s;
    margin-bottom: -22px;
  }}
  .tab:hover {{ color: var(--text-secondary); }}
  .tab.active {{ color: var(--text); border-bottom-color: var(--accent); }}

  /* ── KPI row ── */
  .kpis {{
    display: grid; grid-template-columns: repeat(6, 1fr); gap: 1px;
    background: var(--border-subtle); border: 1px solid var(--border);
    margin-bottom: 32px;
  }}
  .kpi {{
    background: var(--surface); padding: 20px 24px;
  }}
  .kpi-label {{
    font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem;
    color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.1em;
    margin-bottom: 8px;
  }}
  .kpi-val {{
    font-family: 'IBM Plex Mono', monospace; font-size: 1.5rem; font-weight: 600;
    letter-spacing: -0.02em; color: var(--text);
  }}
  .kpi-sub {{
    font-family: 'IBM Plex Mono', monospace; font-size: 0.68rem;
    color: var(--text-dim); margin-top: 4px;
  }}
  .kpi-val.up {{ color: var(--positive); }}
  .kpi-val.down {{ color: var(--negative); }}
  .kpi-val.muted {{ color: var(--text-secondary); }}

  /* ── Chart panels ── */
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1px; background: var(--border-subtle); border: 1px solid var(--border); margin-bottom: 32px; }}
  .panel {{ background: var(--surface); padding: 24px; }}
  .panel.span {{ grid-column: 1 / -1; }}
  .panel-title {{
    font-family: 'IBM Plex Mono', monospace; font-size: 0.68rem;
    color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.08em;
    margin-bottom: 16px; display: flex; align-items: center; gap: 8px;
  }}
  .panel-title::before {{
    content: ''; display: inline-block; width: 3px; height: 12px;
    background: var(--accent); flex-shrink: 0;
  }}

  /* ── Tables ── */
  .table-section {{ margin-bottom: 32px; }}
  .table-header {{
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 0;
    padding: 14px 20px;
    background: var(--surface); border: 1px solid var(--border); border-bottom: none;
  }}
  .table-header h2 {{
    font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem;
    text-transform: uppercase; letter-spacing: 0.08em;
    font-weight: 500; color: var(--text-secondary);
  }}
  .search {{
    background: var(--bg); border: 1px solid var(--border); color: var(--text);
    padding: 6px 12px; font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem;
    width: 200px; outline: none; transition: border-color 0.1s;
  }}
  .search:focus {{ border-color: var(--accent); }}
  .search::placeholder {{ color: var(--text-dim); }}
  .tbl-wrap {{ border: 1px solid var(--border); overflow: hidden; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.78rem; }}
  th {{
    text-align: left; padding: 10px 16px;
    font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem;
    color: var(--text-dim); font-weight: 500; text-transform: uppercase;
    letter-spacing: 0.08em; background: var(--surface-raised);
    border-bottom: 1px solid var(--border); cursor: pointer; user-select: none;
    white-space: nowrap;
  }}
  th:hover {{ color: var(--text-secondary); }}
  th .arrow {{ opacity: 0.3; margin-left: 4px; font-size: 0.55rem; }}
  th.sorted .arrow {{ opacity: 1; color: var(--accent); }}
  td {{
    padding: 9px 16px; border-bottom: 1px solid var(--border-subtle);
    font-family: 'DM Sans', sans-serif; font-size: 0.78rem;
  }}
  tr:last-child td {{ border-bottom: none; }}
  tr {{ background: var(--surface); transition: background 0.05s; }}
  tr:hover {{ background: var(--surface-raised); }}
  .tag {{
    display: inline-block; padding: 2px 8px;
    font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem;
    font-weight: 500; text-transform: uppercase; letter-spacing: 0.06em;
    border: 1px solid;
  }}
  .tag.paid_out {{ color: var(--positive); border-color: rgba(34,197,94,0.25); background: rgba(34,197,94,0.06); }}
  .tag.pending {{ color: var(--warning); border-color: rgba(202,138,4,0.25); background: rgba(202,138,4,0.06); }}
  .tag.new {{ color: var(--accent); border-color: rgba(var(--accent-rgb),0.25); background: rgba(var(--accent-rgb),0.06); }}
  .tag.renewal {{ color: #a78bfa; border-color: rgba(167,139,250,0.25); background: rgba(167,139,250,0.06); }}
  .neg {{ color: var(--negative); }}
  td.mono {{ font-family: 'IBM Plex Mono', monospace; font-variant-numeric: tabular-nums; font-size: 0.74rem; }}
  .empty {{ padding: 32px; text-align: center; color: var(--text-dim); font-size: 0.78rem; }}

  /* ── Responsive ── */
  @media (max-width: 960px) {{
    .grid {{ grid-template-columns: 1fr; }}
    .panel.span {{ grid-column: 1; }}
    .kpis {{ grid-template-columns: repeat(3, 1fr); }}
    header {{ flex-direction: column; align-items: flex-start; gap: 16px; }}
    nav {{ margin-bottom: -22px; }}
  }}
  @media (max-width: 600px) {{
    .wrap {{ padding: 20px 16px; }}
    .kpis {{ grid-template-columns: repeat(2, 1fr); }}
    .kpi {{ padding: 14px 16px; }}
    .kpi-val {{ font-size: 1.2rem; }}
    .tbl-wrap {{ overflow-x: auto; }}
    .search {{ width: 100%; }}
    nav {{ flex-wrap: wrap; }}
  }}
</style>
</head>
<body>
<div class="wrap">

<header>
  <div>
    <div class="brand">
      {logo_html}
      <h1>{brand["name"]} <span>/ revenue</span></h1>
    </div>
    <div class="meta" style="margin-top:6px">Last sync {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
  </div>
  <nav>
    <button class="tab" data-filter="7d" onclick="setFilter('7d')">7d</button>
    <button class="tab" data-filter="30d" onclick="setFilter('30d')">30d</button>
    {f'<button class="tab" data-filter="launch" onclick="setFilter(\'launch\')">{brand["launch_label"]}</button>' if brand["launch_date"] else ""}
    <button class="tab active" data-filter="all" onclick="setFilter('all')">All</button>
  </nav>
</header>

<div class="kpis" id="statsGrid"></div>

<div class="grid">
  <div class="panel span">
    <div class="panel-title">Revenue over time</div>
    <canvas id="revenueChart" height="65"></canvas>
  </div>
  <div class="panel">
    <div class="panel-title">Cumulative net</div>
    <canvas id="cumulativeChart"></canvas>
  </div>
  <div class="panel">
    <div class="panel-title">Monthly breakdown</div>
    <canvas id="monthlyChart"></canvas>
  </div>
  <div class="panel">
    <div class="panel-title">New vs renewals</div>
    <canvas id="memberChart"></canvas>
  </div>
  <div class="panel">
    <div class="panel-title">Price tiers</div>
    <canvas id="tierChart"></canvas>
  </div>
</div>

<div class="table-section">
  <div class="table-header">
    <h2>Payouts</h2>
  </div>
  <div class="tbl-wrap">
    <table id="payoutTable">
      <thead><tr>
        <th onclick="sortTable('payoutTable',0)">ID <span class="arrow">&#9650;</span></th>
        <th onclick="sortTable('payoutTable',1)" class="sorted">Date <span class="arrow">&#9660;</span></th>
        <th onclick="sortTable('payoutTable',2)">Amount <span class="arrow">&#9650;</span></th>
        <th onclick="sortTable('payoutTable',3)">Matched <span class="arrow">&#9650;</span></th>
        <th onclick="sortTable('payoutTable',4)">Unmatched <span class="arrow">&#9650;</span></th>
        <th>Notes</th>
      </tr></thead>
      <tbody id="payoutBody"></tbody>
    </table>
  </div>
</div>

<div class="table-section">
  <div class="table-header">
    <h2>Transactions</h2>
    <input type="text" class="search" id="txnSearch" placeholder="Filter..." oninput="renderTxnTable()">
  </div>
  <div class="tbl-wrap">
    <table id="txnTable">
      <thead><tr>
        <th onclick="sortTxnTable(0)">ID <span class="arrow">&#9650;</span></th>
        <th onclick="sortTxnTable(1)" class="sorted">Date <span class="arrow">&#9660;</span></th>
        <th onclick="sortTxnTable(2)">Member <span class="arrow">&#9650;</span></th>
        <th onclick="sortTxnTable(3)">Type <span class="arrow">&#9650;</span></th>
        <th onclick="sortTxnTable(4)">Gross <span class="arrow">&#9650;</span></th>
        <th onclick="sortTxnTable(5)">Fee <span class="arrow">&#9650;</span></th>
        <th onclick="sortTxnTable(6)">Net <span class="arrow">&#9650;</span></th>
        <th onclick="sortTxnTable(7)">Status <span class="arrow">&#9650;</span></th>
        <th>Payout</th>
      </tr></thead>
      <tbody id="txnBody"></tbody>
    </table>
  </div>
</div>

</div>

<script>
const SYM = '{s}';
const BRAND = {brand_json};
const allTxns = {txns_json};
const allPayouts = {payouts_json};
let currentFilter = BRAND.launch_date ? 'launch' : 'all';
let txnSortCol = 1, txnSortAsc = false;
let filteredTxns = [];

let revenueChart, cumulativeChart, monthlyChart, memberChart, tierChart;

Chart.defaults.color = '#525252';
Chart.defaults.borderColor = '#2a2a2a';
const fontConf = {{ family: "'IBM Plex Mono', monospace", size: 10 }};

function getFilterDate(filter) {{
  if (filter === 'all') return null;
  if (filter === 'launch') return BRAND.launch_date;
  const d = new Date();
  if (filter === '7d') d.setDate(d.getDate() - 7);
  if (filter === '30d') d.setDate(d.getDate() - 30);
  return d.toISOString().slice(0, 10);
}}

function filterData(minDate) {{
  const txns = minDate ? allTxns.filter(t => t.date >= minDate) : [...allTxns];
  const payouts = minDate ? allPayouts.filter(p => p.date >= minDate) : [...allPayouts];
  return {{ txns, payouts }};
}}

function setFilter(f) {{
  currentFilter = f;
  document.querySelectorAll('.tab').forEach(b => b.classList.toggle('active', b.dataset.filter === f));
  render();
}}

function fmt(n) {{ return SYM + n.toLocaleString('en', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }}); }}

function daysBetween(a, b) {{ return Math.floor((new Date(b) - new Date(a)) / 86400000); }}

function render() {{
  const minDate = getFilterDate(currentFilter);
  const {{ txns, payouts }} = filterData(minDate);
  filteredTxns = txns;

  const gross = txns.reduce((s, t) => s + t.amount, 0);
  const fees = txns.reduce((s, t) => s + t.fee, 0);
  const net = txns.reduce((s, t) => s + t.net, 0);
  const paid = payouts.reduce((s, p) => s + p.amount, 0);
  const pendingNet = txns.filter(t => t.status === 'pending').reduce((s, t) => s + t.net, 0);
  const newC = txns.filter(t => t.type === 'new').length;
  const renC = txns.filter(t => t.type === 'renewal').length;
  const totalMembers = newC + renC;

  const monthlyTxns = txns.filter(t => !t.notes.includes('year'));
  const mrr = monthlyTxns.reduce((s, t) => s + t.net, 0) / Math.max(1, new Set(monthlyTxns.map(t => t.date.slice(0,7))).size);

  const periodStart = minDate || (txns.length ? txns.reduce((a, b) => a.date < b.date ? a : b).date : '');
  const daysActive = periodStart ? daysBetween(periodStart, new Date().toISOString().slice(0,10)) : 0;
  const avgPerDay = daysActive > 0 ? (net / daysActive) : 0;

  document.getElementById('statsGrid').innerHTML = `
    <div class="kpi">
      <div class="kpi-label">Net Revenue</div>
      <div class="kpi-val up">${{fmt(net)}}</div>
      <div class="kpi-sub">gross ${{fmt(gross)}}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Fees</div>
      <div class="kpi-val down">${{fmt(fees)}}</div>
      <div class="kpi-sub">${{gross > 0 ? ((fees/gross)*100).toFixed(1) : 0}}% of gross</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Paid Out</div>
      <div class="kpi-val">${{fmt(paid)}}</div>
      <div class="kpi-sub">${{payouts.length}} payout${{payouts.length !== 1 ? 's' : ''}}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Pending</div>
      <div class="kpi-val muted">${{fmt(pendingNet)}}</div>
      <div class="kpi-sub">7-14d settlement</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Members</div>
      <div class="kpi-val">${{totalMembers}}</div>
      <div class="kpi-sub">${{newC}} new / ${{renC}} renewal</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Avg / Day</div>
      <div class="kpi-val">${{fmt(avgPerDay)}}</div>
      <div class="kpi-sub">${{daysActive}}d tracked</div>
    </div>
  `;

  const daily = {{}};
  txns.forEach(t => {{
    if (!daily[t.date]) daily[t.date] = {{ gross: 0, net: 0 }};
    daily[t.date].gross += t.amount;
    daily[t.date].net += t.net;
  }});
  const days = Object.keys(daily).sort();
  const dGross = days.map(d => +daily[d].gross.toFixed(2));
  const dNet = days.map(d => +daily[d].net.toFixed(2));

  let run = 0;
  const cumul = days.map(d => {{ run += daily[d].net; return +run.toFixed(2); }});

  const mo = {{}};
  txns.forEach(t => {{
    const m = t.date.slice(0, 7);
    if (!mo[m]) mo[m] = {{ gross: 0, net: 0, newC: 0, renC: 0 }};
    mo[m].gross += t.amount; mo[m].net += t.net;
    if (t.type === 'new') mo[m].newC++; else mo[m].renC++;
  }});
  const months = Object.keys(mo).sort();

  const tiers = {{}};
  txns.forEach(t => {{
    const iv = t.notes.includes('year') ? '/yr' : '/mo';
    const k = SYM + t.amount.toFixed(0) + iv;
    tiers[k] = (tiers[k] || 0) + 1;
  }});

  if (revenueChart) revenueChart.destroy();
  if (cumulativeChart) cumulativeChart.destroy();
  if (monthlyChart) monthlyChart.destroy();
  if (memberChart) memberChart.destroy();
  if (tierChart) tierChart.destroy();

  const accentRgba = (a) => `rgba(${{BRAND.accent ? [parseInt(BRAND.accent.slice(1,3),16),parseInt(BRAND.accent.slice(3,5),16),parseInt(BRAND.accent.slice(5,7),16)].join(',') : '59,130,246'}},${{a}})`;

  revenueChart = new Chart(document.getElementById('revenueChart'), {{
    type: 'bar',
    data: {{ labels: days, datasets: [
      {{ label: 'Gross', data: dGross, backgroundColor: 'rgba(255,255,255,0.08)', hoverBackgroundColor: 'rgba(255,255,255,0.15)', borderRadius: 1, borderSkipped: false, barPercentage: 0.7 }},
      {{ label: 'Net', data: dNet, backgroundColor: accentRgba(0.55), hoverBackgroundColor: accentRgba(0.75), borderRadius: 1, borderSkipped: false, barPercentage: 0.7 }}
    ] }},
    options: {{ responsive: true, maintainAspectRatio: true,
      plugins: {{ legend: {{ labels: {{ font: fontConf, usePointStyle: true, pointStyle: 'rect', padding: 20 }} }} }},
      scales: {{ x: {{ grid: {{ display: false }}, ticks: {{ font: fontConf, maxRotation: 0, autoSkip: true, maxTicksLimit: 15 }} }},
        y: {{ grid: {{ color: '#222' }}, ticks: {{ font: fontConf, callback: v => SYM + v }} }} }} }}
  }});

  cumulativeChart = new Chart(document.getElementById('cumulativeChart'), {{
    type: 'line',
    data: {{ labels: days, datasets: [{{
      label: 'Cumulative Net', data: cumul,
      borderColor: accentRgba(0.8), backgroundColor: accentRgba(0.05),
      fill: true, tension: 0.3, pointRadius: 0, pointHitRadius: 10, borderWidth: 2
    }}] }},
    options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }},
      scales: {{ x: {{ grid: {{ display: false }}, ticks: {{ font: fontConf, maxTicksLimit: 8 }} }},
        y: {{ grid: {{ color: '#222' }}, ticks: {{ font: fontConf, callback: v => SYM + v }} }} }} }}
  }});

  monthlyChart = new Chart(document.getElementById('monthlyChart'), {{
    type: 'bar',
    data: {{ labels: months, datasets: [
      {{ label: 'Gross', data: months.map(m => +mo[m].gross.toFixed(2)), backgroundColor: 'rgba(255,255,255,0.08)', borderRadius: 1 }},
      {{ label: 'Net', data: months.map(m => +mo[m].net.toFixed(2)), backgroundColor: accentRgba(0.55), borderRadius: 1 }}
    ] }},
    options: {{ responsive: true,
      plugins: {{ legend: {{ labels: {{ font: fontConf, usePointStyle: true, pointStyle: 'rect' }} }} }},
      scales: {{ x: {{ grid: {{ display: false }}, ticks: {{ font: fontConf }} }},
        y: {{ grid: {{ color: '#222' }}, ticks: {{ font: fontConf, callback: v => SYM + v }} }} }} }}
  }});

  memberChart = new Chart(document.getElementById('memberChart'), {{
    type: 'bar',
    data: {{ labels: months, datasets: [
      {{ label: 'New', data: months.map(m => mo[m].newC), backgroundColor: accentRgba(0.55), borderRadius: 1 }},
      {{ label: 'Renewals', data: months.map(m => mo[m].renC), backgroundColor: 'rgba(167,139,250,0.45)', borderRadius: 1 }}
    ] }},
    options: {{ responsive: true,
      plugins: {{ legend: {{ labels: {{ font: fontConf, usePointStyle: true, pointStyle: 'rect' }} }} }},
      scales: {{ x: {{ grid: {{ display: false }}, ticks: {{ font: fontConf }} }},
        y: {{ grid: {{ color: '#222' }}, ticks: {{ font: fontConf, stepSize: 1 }} }} }} }}
  }});

  tierChart = new Chart(document.getElementById('tierChart'), {{
    type: 'doughnut',
    data: {{ labels: Object.keys(tiers), datasets: [{{
      data: Object.values(tiers),
      backgroundColor: [accentRgba(0.65),'rgba(34,197,94,0.55)','rgba(202,138,4,0.55)','rgba(167,139,250,0.55)','rgba(220,38,38,0.55)','rgba(14,165,233,0.55)','rgba(217,70,239,0.55)'],
      borderWidth: 0, spacing: 2
    }}] }},
    options: {{ responsive: true, cutout: '70%',
      plugins: {{ legend: {{ position: 'bottom', labels: {{ font: fontConf, usePointStyle: true, pointStyle: 'rect', padding: 14 }} }} }} }}
  }});

  const pb = document.getElementById('payoutBody');
  if (!payouts.length) {{
    pb.innerHTML = '<tr><td colspan="6" class="empty">No payouts in this period</td></tr>';
  }} else {{
    pb.innerHTML = payouts.sort((a, b) => b.date.localeCompare(a.date)).map(p => `<tr>
      <td class="mono">${{p.id}}</td><td class="mono">${{p.date}}</td><td class="mono">${{fmt(p.amount)}}</td>
      <td class="mono">${{fmt(p.matched)}}</td>
      <td class="mono${{Math.abs(p.unmatched) > 0.01 ? ' neg' : ''}}">${{fmt(p.unmatched)}}</td>
      <td>${{p.notes}}</td></tr>`).join('');
  }}

  renderTxnTable();
}}

function renderTxnTable() {{
  const q = (document.getElementById('txnSearch').value || '').toLowerCase();
  let txns = filteredTxns;
  if (q) txns = txns.filter(t => t.name.toLowerCase().includes(q) || t.id.toLowerCase().includes(q));

  const cols = [t=>t.id, t=>t.date, t=>t.name.toLowerCase(), t=>t.type, t=>t.amount, t=>t.fee, t=>t.net, t=>t.status];
  if (cols[txnSortCol]) {{
    txns = [...txns].sort((a, b) => {{
      const av = cols[txnSortCol](a), bv = cols[txnSortCol](b);
      const cmp = av < bv ? -1 : av > bv ? 1 : 0;
      return txnSortAsc ? cmp : -cmp;
    }});
  }}

  const body = document.getElementById('txnBody');
  if (!txns.length) {{
    body.innerHTML = '<tr><td colspan="9" class="empty">No transactions found</td></tr>';
    return;
  }}
  body.innerHTML = txns.map(t => `<tr>
    <td class="mono">${{t.id}}</td><td class="mono">${{t.date}}</td><td>${{t.name}}</td>
    <td><span class="tag ${{t.type}}">${{t.type}}</span></td>
    <td class="mono">${{fmt(t.amount)}}</td><td class="mono">${{fmt(t.fee)}}</td><td class="mono">${{fmt(t.net)}}</td>
    <td><span class="tag ${{t.status}}">${{t.status.replace('_',' ')}}</span></td>
    <td class="mono">${{t.payout_id}}</td></tr>`).join('');
}}

function sortTxnTable(col) {{
  if (txnSortCol === col) txnSortAsc = !txnSortAsc;
  else {{ txnSortCol = col; txnSortAsc = col <= 2; }}
  renderTxnTable();
  document.querySelectorAll('#txnTable th').forEach((th, i) => {{
    th.classList.toggle('sorted', i === col);
    const icon = th.querySelector('.arrow');
    if (icon) icon.innerHTML = (i === col && txnSortAsc) ? '&#9650;' : '&#9660;';
  }});
}}

function sortTable(tableId, col) {{
  const table = document.getElementById(tableId);
  const body = table.querySelector('tbody');
  const rows = Array.from(body.querySelectorAll('tr'));
  const asc = table.dataset.sortCol == col ? table.dataset.sortAsc !== 'true' : false;
  table.dataset.sortCol = col; table.dataset.sortAsc = asc;
  rows.sort((a, b) => {{
    const av = a.cells[col].textContent, bv = b.cells[col].textContent;
    const an = parseFloat(av.replace(/[^0-9.-]/g, '')), bn = parseFloat(bv.replace(/[^0-9.-]/g, ''));
    const cmp = isNaN(an) ? av.localeCompare(bv) : an - bn;
    return asc ? cmp : -cmp;
  }});
  rows.forEach(r => body.appendChild(r));
}}

document.querySelectorAll('.tab').forEach(b => {{
  b.classList.toggle('active', b.dataset.filter === currentFilter);
}});
render();
</script>
</body>
</html>"""

    dashboard_path = DATA_DIR / "dashboard.html"
    with open(dashboard_path, "w") as f:
        f.write(html)

    if "--no-open" not in args:
        subprocess.run(["open", str(dashboard_path)])
    print(f"Dashboard generated: {dashboard_path}")


def cmd_help(args):
    """Show available commands."""
    s = sym()
    print("Skool Sales Tracker\n")
    print(f"Currency: {DEFAULT_CURRENCY} ({s})  |  Fees: {STRIPE_RATE*100:.1f}% + ${STRIPE_FIXED:.2f} per txn\n")
    print("Commands:")
    print("  sale <name> <amount> [date] [notes]      Log a new member sale")
    print("  renewal <name> <amount> [date] [notes]    Log a renewal")
    print("  bulk                                      Bulk-add transactions interactively")
    print("  sync                                      Pull latest members from Skool API")
    print("  import <csv_path>                         Import from Skool CSV export")
    print("  payout <amount> [date] [notes]            Log a payout & auto-match (by net amount)")
    print("  status                                    Summary + next payout estimate")
    print("  list [all|pending|paid_out|new|renewal]   List transactions")
    print("  payouts                                   List all payouts")
    print("  summary [YYYY-MM]                         Monthly breakdown report")
    print("  dashboard                                 Open visual dashboard in browser")
    print("  help                                      Show this help")
    print(f"\nDates default to today. Amounts in {DEFAULT_CURRENCY} (no {s} sign).")
    print("Names with spaces: use quotes or underscores (e.g., John_Smith)")


COMMANDS = {
    "sale": cmd_sale,
    "renewal": cmd_renewal,
    "bulk": cmd_bulk,
    "payout": cmd_payout,
    "status": cmd_status,
    "list": cmd_list,
    "payouts": cmd_payouts,
    "summary": cmd_summary,
    "sync": cmd_sync,
    "import": cmd_import,
    "dashboard": cmd_dashboard,
    "help": cmd_help,
}


def main():
    if len(sys.argv) < 2:
        cmd_help([])
        return
    cmd = sys.argv[1].lower()
    if cmd not in COMMANDS:
        print(f"Unknown command: {cmd}")
        cmd_help([])
        return
    COMMANDS[cmd](sys.argv[2:])


if __name__ == "__main__":
    main()
