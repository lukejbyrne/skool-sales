# Build Your Skool Revenue Tracker with Claude Code

**What you'll build:** A fully automated revenue tracking system for your Skool community that syncs your member data daily, tracks every sale and renewal, reconciles against your Wednesday payouts, and gives you a live visual dashboard — all in under 30 minutes using Claude Code.

**The problem:** Skool gives you a lump-sum payout every Wednesday, but no breakdown of which sales made up that payout. You can see members on your members page, and you can see payouts in your balance — but there's no connection between the two. So you're left guessing whether the numbers add up, and you have zero visibility into fees, pending settlements, or revenue trends.

**What you'll end up with:**
- A Python CLI that tracks every sale, renewal, and payout
- Auto-sync from Skool (no manual CSV exports)
- Payout reconciliation that matches individual sales to each Wednesday payout
- A dark-mode dashboard with charts, filters (7D / 30D / custom), and full transaction tables
- Daily cron job that keeps everything up to date
- Hosted on Netlify so you can check your dashboard from anywhere

**Reference code:** https://github.com/lukejbyrne/skool-sales

---

### Prerequisites

- Claude Code installed (`npm install -g @anthropic-ai/claude-code`)
- A Skool community with paying members
- A GitHub account
- A Netlify account (free tier is fine)

---

### Step 1: Set Up the Project (2 min)

Open your terminal and create the project:

```bash
mkdir skool-sales && cd skool-sales
claude
```

Tell Claude:

> Build me a Skool sales tracker. I need a Python CLI tool (tracker.py) that:
> - Logs new member sales and renewals with amounts and dates
> - Tracks processing fees (Stripe: 2.9% + $0.30 per transaction)
> - Logs Wednesday payouts and auto-matches them to pending transactions (FIFO by date)
> - Shows status with pending amounts and next payout estimates
> - Has a monthly summary report
> - Stores everything in CSV files under a data/ directory
> - Currency should be USD
>
> Commands I want: sale, renewal, bulk, payout, status, list, payouts, summary, help

Claude will generate the full `tracker.py`. Test it:

```bash
python3 tracker.py help
python3 tracker.py sale Test_User 99
python3 tracker.py status
```

---

### Step 2: Import Your Existing Members (2 min)

Go to your Skool community > Members > Export CSV.

Then tell Claude:

> Add an import command that reads the Skool community_members CSV export. It should:
> - Parse FirstName, LastName, JoinedDate, Price, and Recurring Interval columns
> - Skip free members ($0 or blank price)
> - Deduplicate by name + date so I can re-import safely
> - Log each imported member with their net amount after fees

Import your data:

```bash
python3 tracker.py import ~/Downloads/community_members.csv
```

---

### Step 3: Verify the Fee Model (5 min)

This is the key insight — Skool's payout page shows your payout history. Compare a payout amount against the members who joined 7-14 days before it.

**The fee formula:** Each transaction is charged Stripe's standard 2.9% + $0.30. So a $9 sale nets you $8.44, a $19 sale nets $18.15, etc.

Log your historical payouts:

```bash
python3 tracker.py payout 18.15 2025-03-04 "Wednesday payout"
```

If the auto-match shows $0.00 unmatched — your fee model is correct. If not, adjust the fee constants in the script.

---

### Step 4: Add the Visual Dashboard (5 min)

Tell Claude:

> Add a dashboard command that generates an HTML file with Chart.js. Include:
> - KPI cards: gross revenue, net revenue, fees, paid out, pending, member counts
> - Revenue over time bar chart (daily, gross vs net)
> - Cumulative net revenue line chart
> - Monthly breakdown bar chart
> - New vs renewals bar chart
> - Price tier doughnut chart
> - Payout table and full transaction table
> - Filter tabs: 7D, 30D, All Time, and a custom one for your community launch date
> - All filtering should be client-side (embed data as JSON, rebuild charts on filter click)
> - Dark mode
> - Open the HTML in the browser when generated

```bash
python3 tracker.py dashboard
```

Your dashboard opens in the browser with all your data visualised.

---

### Step 5: Set Up Auto-Sync from Skool (5 min)

Instead of manually exporting CSVs, you can pull member data directly from Skool using your auth cookie.

**Get your auth token:**
1. Go to skool.com and log in
2. Open browser DevTools (F12) > Application > Cookies > skool.com
3. Copy the `auth_token` value (it's a long JWT string)
4. Also copy `client_id`

Create a `.env` file:

```bash
echo "SKOOL_AUTH_TOKEN=<paste_your_token>" > .env
echo "SKOOL_GROUP=<your_group_slug>" >> .env
echo "SKOOL_CLIENT_ID=<paste_client_id>" >> .env
```

Tell Claude:

> Add a sync command that:
> - Reads auth token from .env
> - Fetches the members page from Skool (the __NEXT_DATA__ JSON has all member data)
> - Parses each member's price from the mmbp metadata field (amount is in cents)
> - Imports new members the same way the import command does
> - Handles pagination if there are more than 30 members

Test it:

```bash
python3 tracker.py sync
```

---

### Step 6: Daily Cron Job (2 min)

Create `sync.sh`:

```bash
#!/bin/bash
cd /path/to/skool-sales
/usr/bin/python3 tracker.py sync >> data/sync.log 2>&1
/usr/bin/python3 tracker.py dashboard --no-open >> data/sync.log 2>&1
echo "--- $(date) ---" >> data/sync.log
```

```bash
chmod +x sync.sh
```

Add to your crontab (runs daily at 9am):

```bash
crontab -e
# Add this line:
0 9 * * * /path/to/skool-sales/sync.sh
```

Check logs anytime:

```bash
cat data/sync.log
```

---

### Step 7: Push to GitHub (2 min)

```bash
git init
```

Make sure `.gitignore` includes:
```
.env
data/
```

```bash
git add -A
git commit -m "Skool revenue tracker"
gh repo create skool-sales --public --push
```

Your token stays local. The code is shareable.

---

### Step 8: Host Dashboard on Netlify (5 min)

Since the dashboard is a single static HTML file, Netlify is perfect.

Tell Claude:

> Add a deploy command that:
> - Regenerates the dashboard
> - Uses the Netlify CLI to deploy data/dashboard.html as a static site
> - Prints the live URL

Or do it manually:

1. Install Netlify CLI: `npm install -g netlify-cli`
2. `netlify login`
3. `netlify deploy --prod --dir=data --site=your-site-name`

Add the deploy to your cron script so the hosted dashboard updates daily too.

Update `sync.sh`:
```bash
#!/bin/bash
cd /path/to/skool-sales
/usr/bin/python3 tracker.py sync >> data/sync.log 2>&1
/usr/bin/python3 tracker.py dashboard --no-open >> data/sync.log 2>&1
netlify deploy --prod --dir=data >> data/sync.log 2>&1
echo "--- $(date) ---" >> data/sync.log
```

---

### What You've Built

| Feature | How |
|---|---|
| Every sale tracked | Auto-synced from Skool daily |
| Fees calculated | Stripe 2.9% + $0.30 per transaction |
| Payout reconciliation | Auto-matched FIFO when you log payouts |
| Visual dashboard | Chart.js, dark mode, filterable |
| Always up to date | Cron job syncs + deploys daily |
| Accessible anywhere | Hosted on Netlify |
| Secure | Token stays in .env, never committed |

---

### Ongoing Usage

**When you get a Wednesday payout:**
```bash
python3 tracker.py payout <amount> <date>
```

**Check status anytime:**
```bash
python3 tracker.py status
```

**Or just open your Netlify URL.**

---

### Customisation Ideas

- Add Slack/Discord notifications when a new member joins
- Track refunds and chargebacks
- Add MRR (monthly recurring revenue) calculations
- Currency conversion tracking (USD to GBP) using live exchange rates
- Multiple Skool communities in one dashboard
