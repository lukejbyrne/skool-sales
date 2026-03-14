# Skool Revenue Tracker

Track every sale, renewal, and Wednesday payout from your Skool community. Auto-syncs daily, reconciles fees, and gives you a live dashboard you can host anywhere.

**GitHub:** https://github.com/lukejbyrne/skool-sales

--

### What It Does

- Tracks every member sale and renewal with Stripe fee calculations (2.9% + $0.30)
- Auto-syncs member data from Skool daily (no manual CSV exports)
- Matches individual sales to your Wednesday payouts (FIFO reconciliation)
- Generates a dark-mode dashboard with charts, filters, and transaction tables
- Hosts on Netlify so you can check it from your phone

--

### Setup (10 min)

**1. Clone the repo**

```bash
git clone https://github.com/lukejbyrne/skool-sales.git
cd skool-sales
```

**2. Get your Skool credentials**

Go to skool.com, open DevTools (F12), then Application, then Cookies, then skool.com. Copy `auth_token` and `client_id`.

**3. Create your `.env` file**

```bash
SKOOL_AUTH_TOKEN=<your_auth_token>
SKOOL_GROUP=<your_group_slug>
SKOOL_CLIENT_ID=<your_client_id>

BRAND_NAME=Your Community Name
BRAND_LOGO=
BRAND_ACCENT=#3b82f6
BRAND_LAUNCH_DATE=2025-01-01
BRAND_LAUNCH_LABEL=Launch
```

Replace the brand values with your own. The launch date adds a filter tab to your dashboard.

**4. Sync and view**

```bash
python3 tracker.py sync
python3 tracker.py dashboard
```

--

### Daily Automation

Make `sync.sh` executable and add it to your crontab:

```bash
chmod +x sync.sh
crontab -e
# Add:
0 9 * * * /path/to/skool-sales/sync.sh
```

This syncs your members and regenerates the dashboard every morning.

--

### Hosting on Netlify

```bash
npm install -g netlify-cli
netlify login
netlify deploy -prod -dir=data
```

Add `netlify deploy -prod -dir=data >> data/sync.log 2>&1` to your `sync.sh` so it deploys automatically with each sync.

--

### Logging Payouts

When you get your Wednesday payout from Skool:

```bash
python3 tracker.py payout <amount> <date>
```

The tracker auto-matches it against pending transactions. If unmatched shows $0.00, everything reconciles.

--

### All Commands

- `sync` - Pull latest members from Skool
- `dashboard` - Generate and open the visual dashboard
- `payout <amount> [date]` - Log a payout and auto-match
- `status` - Summary with pending amounts
- `list` - List all transactions
- `payouts` - List all payouts
- `summary [YYYY-MM]` - Monthly breakdown
- `sale <name> <amount>` - Manually log a sale
- `renewal <name> <amount>` - Manually log a renewal
- `import <csv>` - Import from Skool CSV export
