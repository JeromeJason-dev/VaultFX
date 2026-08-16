import sqlite3
from pathlib import Path
from contextlib import contextmanager


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "finance_tracker.db"

DEFAULT_CATEGORIES = [
    ("Food & Dining", "personal"),
    ("Transport", "personal"),
    ("Housing", "personal"),
    ("Utilities", "personal"),
    ("Entertainment", "personal"),
    ("Health", "personal"),
    ("Shopping", "personal"),
    ("Travel", "personal"),
    ("Education", "personal"),
    ("Other", "personal"),
    ("COGS", "business"),
    ("Payroll", "business"),
    ("Software & Subscriptions", "business"),
    ("Marketing", "business"),
    ("Sales Revenue", "business"),
]

# Thresholds used for budget warning badges in the UI.
BUDGET_WARNING_THRESHOLD = 0.80
BUDGET_OVER_THRESHOLD = 1.00

# Role hierarchy 
ROLES = ("viewer", "editor", "admin", "owner")
ROLE_RANK = {role: idx for idx, role in enumerate(ROLES)}


class DatabaseManager:
    """Owns the SQLite connection and schema lifecycle."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self._initialize_schema()
        self._run_migrations()

    def execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        """Run an INSERT/UPDATE/DELETE (or DDL) statement and commit."""
        cur = self.conn.execute(query, params)
        self.conn.commit()
        return cur

    def query(self, query: str, params: tuple = ()) -> list[sqlite3.Row]:
        """Run a SELECT and return all rows."""
        return self.conn.execute(query, params).fetchall()

    def query_one(self, query: str, params: tuple = ()) -> sqlite3.Row | None:
        return self.conn.execute(query, params).fetchone()

    @contextmanager
    def transaction(self):
        cur = self.conn.cursor()
        try:
            yield cur
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def close(self):
        self.conn.close()

    # Schema

    def _initialize_schema(self):
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS Users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT NOT NULL UNIQUE,
                password_hash TEXT,
                base_currency TEXT NOT NULL DEFAULT 'USD',
                created_at    TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- A shared "book" of categories/transactions. Membership +
            -- role live in LedgerMembers below.
            CREATE TABLE IF NOT EXISTS Ledgers (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL,
                base_currency TEXT NOT NULL DEFAULT 'USD',
                created_by    INTEGER NOT NULL REFERENCES Users(id),
                created_at    TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS LedgerMembers (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ledger_id INTEGER NOT NULL REFERENCES Ledgers(id) ON DELETE CASCADE,
                user_id   INTEGER NOT NULL REFERENCES Users(id) ON DELETE CASCADE,
                role      TEXT NOT NULL DEFAULT 'viewer'
                          CHECK (role IN ('owner', 'admin', 'editor', 'viewer')),
                joined_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE (ledger_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS Categories (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                ledger_id      INTEGER NOT NULL REFERENCES Ledgers(id) ON DELETE CASCADE,
                name           TEXT NOT NULL,
                monthly_budget REAL NOT NULL DEFAULT 0,
                category_type  TEXT NOT NULL DEFAULT 'personal'
                               CHECK (category_type IN ('personal', 'business')),
                UNIQUE (ledger_id, name)
            );

            CREATE TABLE IF NOT EXISTS Transactions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ledger_id     INTEGER NOT NULL REFERENCES Ledgers(id) ON DELETE CASCADE,
                user_id       INTEGER NOT NULL REFERENCES Users(id),
                category_id   INTEGER NOT NULL,
                amount        REAL NOT NULL,
                currency      TEXT NOT NULL DEFAULT 'USD',
                txn_type      TEXT NOT NULL DEFAULT 'expense'
                              CHECK (txn_type IN ('income', 'expense')),
                rate_to_base  REAL NOT NULL DEFAULT 1.0,
                base_currency TEXT NOT NULL DEFAULT 'USD',
                description   TEXT,
                txn_date      TEXT NOT NULL DEFAULT (date('now')),
                recurring_id  INTEGER,
                created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (category_id) REFERENCES Categories(id) ON DELETE RESTRICT
            );

            -- A repeating-transaction rule. RecurringTransactionDAO.generate_due()
            -- materializes real Transactions rows from these as they come due.
            CREATE TABLE IF NOT EXISTS RecurringTransactions (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                ledger_id      INTEGER NOT NULL REFERENCES Ledgers(id) ON DELETE CASCADE,
                category_id    INTEGER NOT NULL REFERENCES Categories(id) ON DELETE RESTRICT,
                amount         REAL NOT NULL,
                currency       TEXT NOT NULL DEFAULT 'USD',
                txn_type       TEXT NOT NULL DEFAULT 'expense'
                               CHECK (txn_type IN ('income', 'expense')),
                description    TEXT,
                frequency      TEXT NOT NULL DEFAULT 'monthly'
                               CHECK (frequency IN ('daily', 'weekly', 'monthly', 'yearly')),
                interval_count INTEGER NOT NULL DEFAULT 1,
                start_date     TEXT NOT NULL,
                end_date       TEXT,
                next_run_date  TEXT NOT NULL,
                active         INTEGER NOT NULL DEFAULT 1,
                created_by     INTEGER NOT NULL REFERENCES Users(id),
                created_at     TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_transactions_date ON Transactions(txn_date);
            CREATE INDEX IF NOT EXISTS idx_transactions_category ON Transactions(category_id);
            CREATE INDEX IF NOT EXISTS idx_transactions_type ON Transactions(txn_type);
            CREATE INDEX IF NOT EXISTS idx_ledgermembers_user ON LedgerMembers(user_id);
            CREATE INDEX IF NOT EXISTS idx_recurring_ledger ON RecurringTransactions(ledger_id);
            """
        )
        self.conn.commit()

    def _run_migrations(self):
        user_cols = {row["name"] for row in self.query("PRAGMA table_info(Users)")}
        if "password_hash" not in user_cols:
            self.execute("ALTER TABLE Users ADD COLUMN password_hash TEXT")

        txn_cols = {row["name"] for row in self.query("PRAGMA table_info(Transactions)")}
        txn_columns_to_add = {
            "txn_type": "TEXT NOT NULL DEFAULT 'expense'",
            "rate_to_base": "REAL NOT NULL DEFAULT 1.0",
            "base_currency": "TEXT NOT NULL DEFAULT 'USD'",
            "recurring_id": "INTEGER",
            "ledger_id": "INTEGER",
        }
        for col, ddl in txn_columns_to_add.items():
            if col not in txn_cols:
                self.execute(f"ALTER TABLE Transactions ADD COLUMN {col} {ddl}")

        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_ledger ON Transactions(ledger_id)")
        self.conn.execute("DROP TABLE IF EXISTS ExchangeRateHistory")
        self.conn.commit()

        cat_cols = {row["name"] for row in self.query("PRAGMA table_info(Categories)")}
        if "ledger_id" not in cat_cols:
            self._migrate_to_ledgers()

    def _migrate_to_ledgers(self):
        """
        One-time migration for databases created before shared Ledgers
        existed. Gives every existing user their own personal ledger
        (as 'owner'), clones the old global categories into it, and
        re-points that user's transactions at the new ledger + cloned
        categories. Nothing is deleted.
        """
        old_categories = self.query("SELECT * FROM Categories")
        users = self.query("SELECT * FROM Users")

        with self.transaction() as cur:
            cur.execute("ALTER TABLE Categories RENAME TO Categories_old")
            cur.execute(
                """
                CREATE TABLE Categories (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    ledger_id      INTEGER NOT NULL REFERENCES Ledgers(id) ON DELETE CASCADE,
                    name           TEXT NOT NULL,
                    monthly_budget REAL NOT NULL DEFAULT 0,
                    category_type  TEXT NOT NULL DEFAULT 'personal'
                                   CHECK (category_type IN ('personal', 'business')),
                    UNIQUE (ledger_id, name)
                )
                """
            )

            for user in users:
                cur.execute(
                    "INSERT INTO Ledgers (name, base_currency, created_by) VALUES (?, ?, ?)",
                    (f"{user['username']}'s Ledger", user["base_currency"], user["id"]),
                )
                ledger_id = cur.lastrowid
                cur.execute(
                    "INSERT INTO LedgerMembers (ledger_id, user_id, role) VALUES (?, ?, 'owner')",
                    (ledger_id, user["id"]),
                )

                old_to_new_category = {}
                for old_cat in old_categories:
                    cur.execute(
                        """
                        INSERT INTO Categories (ledger_id, name, monthly_budget, category_type)
                        VALUES (?, ?, ?, ?)
                        """,
                        (ledger_id, old_cat["name"], old_cat["monthly_budget"], old_cat["category_type"]),
                    )
                    old_to_new_category[old_cat["id"]] = cur.lastrowid

                cur.execute("SELECT id, category_id FROM Transactions WHERE user_id = ?", (user["id"],))
                for txn in cur.fetchall():
                    new_cat_id = old_to_new_category.get(txn["category_id"])
                    if new_cat_id is None:
                        continue  
                    cur.execute(
                        "UPDATE Transactions SET ledger_id = ?, category_id = ? WHERE id = ?",
                        (ledger_id, new_cat_id, txn["id"]),
                    )

            cur.execute("DROP TABLE Categories_old")