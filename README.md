# VaultFX

A desktop expense/income tracker built with **Python, SQLite, and Tkinter**. Record
income and expenses, organize them by custom personal/business categories, set monthly
budgets with alert badges, and see everything converted into any currency using live
exchange rates with historical rate locking for auditability.

## Description

The app opens on a **Login screen** (the landing page). From there you can sign in to
an existing account, or switch to **Register** to create a new one. Once signed in, the
tracker itself is your personal **dashboard** — everything you see (transactions,
categories, budgets, reports) is scoped to your account.


## Features

### Accounts (Login & Registration)
- **Login is the landing page** — the app opens on a sign-in screen, not the tracker
- **Register** a new account (username, password, starting base currency) from a link
  on the Login screen; you're signed in automatically right after registering
- Passwords are stored as **salted PBKDF2-SHA256 hashes** — never in plaintext — and
  compared with a constant-time check
- **Log Out** (top of the dashboard) returns you to the Login screen without closing
  the app, so someone else can sign in or you can switch accounts
- Multi-user by design: every category/transaction/report is scoped to `user_id`, so
  each account has its own independent set of data

### Expanded Financial Engine
- **Income & Expense Tracking** — every transaction is tagged `income` or `expense`;
  the summary panel shows Income, Expenses, and **Net Cash Flow** (Income − Expenses)
- **Category Budgets & Alerts** — set a monthly budget per category; the summary table
  color-codes and labels each row: OK (green), **⚠ 80%+ of budget** (yellow), or
  **⚠ Over budget (100%+)** (red)
- **Custom Categories** — add/edit/delete categories via **Manage Categories…**, each
  tagged `personal` (e.g. Groceries) or `business` (e.g. COGS, Payroll)
- **Financial Reports & Exports** — the **Reports & Export…** window shows a monthly
  P&L summary, a category-breakdown bar chart, and a **CSV export** of filtered
  transactions

### Dynamic Base Currency
- Set your own base currency (KES, USD, EUR, …) from **Save Base Currency** — you're
  never locked into USD
- Foreign-currency transactions are normalized into your base currency automatically

### Historical Rate Locking (Auditability)
- The exact exchange rate (`rate_to_base`) active at the moment a transaction is
  entered is locked into the database, forever
- Past transactions' converted value **never changes**, even if live rates move later
  or you switch your base currency — the "In Base Cur." column in the transaction
  table shows this locked, audited amount

### Live Exchange Rates (Online Application)
This app is **online-only**: every currency conversion — and every rate that gets
locked onto a transaction — is a **live API call** to `open.er-api.com`, made at
the moment you need it. There is no local disk cache and no database of past
rates to fall back on. If you're offline, adding/editing a transaction or viewing
converted totals will show a clear error asking you to reconnect and try again.


## Project Structure

```
finance_tracker/
│
├── backend/
│   ├── __init__.py
│   ├── db.py                # DatabaseManager: SQLite connection + schema init
│   ├── dao.py                # DAO classes: parameterized CRUD + aggregation queries
│   └── currency_service.py   # Live exchange-rate API integration + TTL caching
│
├── gui/
│   ├── __init__.py
│   ├── auth.py                # Login (landing page) + Registration screens
│   └── app.py                 # Tkinter dashboard UI: forms, filters, Treeview tables
│
├── main.py                   # Application entry point (Login/Register ⇄ Dashboard loop)
└── requirements.txt          # Python dependencies
```


## Requirements

- Python 3.10+ 
- **An active internet connection is required.** This is an online application:
  currency conversion and rate-locking on transactions always call the live
  exchange-rate API, with no offline mode


## Setup

1. **Clone**, then move into the folder:
   ```bash
   cd finance_tracker
   ```

2. **(Recommended) Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate      # Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
   > Tkinter ships with most standard Python installs. On some Linux
   > distributions you may need to install it separately, e.g.:
   > `sudo apt-get install python3-tk`

4. **Run the app:**
   ```bash
   python main.py
   ```

On first launch, a SQLite database file (`finance_tracker.db`) is created
automatically in the project root and seeded with 15 default categories
(10 personal, 5 business) shared across accounts. The app opens on the
**Login screen** — click **Register** to create your first account.


## Usage

### Signing up / signing in
- On first run, click **Register** on the Login screen, choose a username,
  starting base currency, and a password (min. 6 characters), then submit —
  you're taken straight into the dashboard, already signed in.
- On later runs, enter your username and password on the Login screen and
  click **Sign In**.
- Click **Log Out** at the top of the dashboard at any time to return to the
  Login screen (the app keeps running — someone else can sign in, or you can
  log back in).

### Adding a transaction
Fill in **Amount**, **Currency**, **Type** (Income/Expense), **Category**,
**Date**, and **Description** in the top form, then click **Add Transaction**.
The current exchange rate from that currency into your base currency is
fetched **live** at that moment and **locked** onto the transaction.

### Editing / deleting
Click a row in the transactions table to load it into the form, then click
**Update Selected** or **Delete Selected**. Updating a transaction re-locks
its rate as of the update time.

### Filtering
Use the **Filter & Convert** bar to narrow the table by category, income/
expense type, month, or a search term, then click **Apply Filters** (or
**Clear Filters** to reset).

### Base currency & display currency
- **Base currency** is your accounting currency, stored on your user profile.
  Change it any time with **Save Base Currency** — existing transactions keep
  their originally locked rate (see Historical Rate Locking above).
- **Show totals in** only affects how the summary panel is *displayed*; it
  does not change any stored data. Click **Refresh Rates** to re-convert.

### Managing categories
Click **Manage Categories…** to add, rename, re-tag (personal/business), or
set the monthly budget for any category, or delete ones you don't use.

### Reports & export
Click **Reports & Export…** for a given month to see:
- A **P&L summary** (income, expenses, net) in your chosen currency
- A **category breakdown bar chart** of that month's expenses
- An **Export Filtered CSV…** button to save transactions to disk, including
  each row's original amount/currency, locked rate, and base-currency value


## Database Schema

| Table          | Key Columns                                                                                                          |
|-----------------|------------------------------------------------------------------------------------------------------------------------|
| `Users`        | `id`, `username`, `password_hash`, (`'salt$hexdigest'`), `base_currency`, `created_at`           |
| `Categories`   | `id`, `name`, `monthly_budget`, `category_type` (`personal`/`business`)                                              |
| `Transactions` | `id`, `user_id` (FK), `category_id` (FK), `amount`, `currency`, `txn_type` (`income`/`expense`), `rate_to_base`, `base_currency`, `description`, `txn_date` |

Foreign keys are enforced (`PRAGMA foreign_keys = ON`), with `ON DELETE CASCADE`
on `Transactions.user_id` and `ON DELETE RESTRICT` on `Transactions.category_id`
(so a category in use can't be deleted out from under existing transactions).

`Transactions.rate_to_base` + `Transactions.base_currency` are what implement
**historical rate locking**: they're written once (from a live API call), at
entry/edit time, and never recalculated — so a category's or month's total
(`SUM(amount * rate_to_base)`) is always the audited, historically-accurate
figure, regardless of what live rates or your base currency do afterward.



## Currency API (Live, Online Only)

Exchange rates come from the free, keyless endpoint:
```
https://open.er-api.com/v6/latest/<BASE_CURRENCY>
```

`CurrencyService` makes **one live HTTP request per rate lookup** — there is
no in-memory cache, no on-disk cache file, and no database table of past
rates. Every conversion you see in the UI, and every `rate_to_base` locked
onto a transaction, reflects the exchange rate at that exact moment.

To swap in a different provider (e.g. one that requires an API key), edit
`BASE_URL` and `_fetch_from_api()` in `backend/currency_service.py` — the
rest of the app is unaffected since it only calls `get_rates()` / `get_rate()`
/ `convert()`.


## Future Roadmap

Some natural next steps, with the relevant hook already in place:

- **Multi-user support** — the schema and DAOs already key everything off
  `user_id`; the GUI just needs a login/user-switcher instead of hardcoding
  `default_user`.
- **Richer charts** — `TransactionDAO.monthly_totals()` and `monthly_pl()`
  return month-over-month figures ready to feed into a charting library
  (e.g. `matplotlib`) for trend visualizations beyond the built-in bar chart.
- **PDF export** — `TransactionDAO.export_transactions_csv()` already builds
  the row data; swap the CSV writer for a PDF report generator.


## Troubleshooting

| Issue | Likely cause / fix |
|---|---|
| `ModuleNotFoundError: No module named 'requests'` | Run `pip install -r requirements.txt` |
| Tkinter window doesn't open / `ModuleNotFoundError: tkinter` | Install your OS's Tk package (see Setup step 3) |
| Currency conversion shows a warning popup | No internet connection, the live API is down, or it timed out — this is an online-only app with no offline fallback, so reconnect and try again |
| "Incorrect username or password" on Login | Double-check spelling/case; if you're on a database from before accounts existed, the old `default_user` has no password set and can't log in — register a new account instead |
| Old data / categories not showing up | Delete `finance_tracker.db` to reset ( this erases all transactions). Normally this isn't needed — the app auto-migrates old databases in place. |


## License

This project is licensed by the MIT license.
