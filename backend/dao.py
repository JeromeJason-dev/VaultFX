from __future__ import annotations

import csv
import hashlib
import io
import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from backend.db import (
    DatabaseManager,
    BUDGET_WARNING_THRESHOLD,
    BUDGET_OVER_THRESHOLD,
    DEFAULT_CATEGORIES,
    ROLE_RANK,
)

# Simple data containers 

@dataclass
class Category:
    id: int
    ledger_id: int
    name: str
    monthly_budget: float
    category_type: str = "personal"


@dataclass
class Transaction:
    id: int
    ledger_id: int
    user_id: int
    category_id: int
    category_name: str
    amount: float
    currency: str
    txn_type: str
    rate_to_base: float
    base_currency: str
    description: str
    txn_date: str
    recurring_id: int | None = None
    added_by_username: str = ""

    @property
    def base_amount(self) -> float:
        return self.amount * self.rate_to_base

    @property
    def signed_base_amount(self) -> float:
        return self.base_amount if self.txn_type == "income" else -self.base_amount


@dataclass
class RecurringRule:
    id: int
    ledger_id: int
    category_id: int
    category_name: str
    amount: float
    currency: str
    txn_type: str
    description: str
    frequency: str
    interval_count: int
    start_date: str
    end_date: str | None
    next_run_date: str
    active: bool


# UserDAO

class UserDAO:
    
    _PBKDF2_ITERATIONS = 200_000

    def __init__(self, db: DatabaseManager):
        self.db = db

    # ---- Password hashing helpers --------

    @classmethod
    def _hash_password(cls, password: str, salt: str | None = None) -> str:
        salt = salt or secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), cls._PBKDF2_ITERATIONS
        )
        return f"{salt}${digest.hex()}"

    @classmethod
    def _password_matches(cls, password: str, stored_hash: str | None) -> bool:
        if not stored_hash or "$" not in stored_hash:
            return False
        salt, _ = stored_hash.split("$", 1)
        candidate = cls._hash_password(password, salt)
        return secrets.compare_digest(candidate, stored_hash)

    # ---- Registration & login ------
    def get_by_username(self, username: str):
        return self.db.query_one(
            "SELECT * FROM Users WHERE username = ?", (username.strip(),)
        )

    def get_by_id(self, user_id: int):
        return self.db.query_one("SELECT * FROM Users WHERE id = ?", (user_id,))

    def create_user(self, username: str, password: str, base_currency: str = "USD") -> int:
        username = username.strip()
        if not username:
            raise ValueError("Username cannot be empty.")
        if not password or len(password) < 6:
            raise ValueError("Password must be at least 6 characters.")
        if self.get_by_username(username):
            raise ValueError(f"Username '{username}' is already taken.")

        password_hash = self._hash_password(password)
        try:
            cur = self.db.execute(

                (username, password_hash, base_currency.upper() or "USD"),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Username '{username}' is already taken.") from exc
        return cur.lastrowid

    def verify_credentials(self, username: str, password: str):
        
        user = self.get_by_username(username)
        if user is None or not self._password_matches(password, user["password_hash"]):
            return None
        return user

    def set_base_currency(self, user_id: int, currency: str):
        self.db.execute(
            "UPDATE Users SET base_currency = ? WHERE id = ?",
            (currency.upper(), user_id),
        )

    def get_base_currency(self, user_id: int) -> str:
        row = self.db.query_one("SELECT base_currency FROM Users WHERE id = ?", (user_id,))
        return row["base_currency"] if row else "USD"


# LedgerDAO -- shared ledgers + role-based membership

class LedgerDAO:
   
    def __init__(self, db: DatabaseManager, user_dao: UserDAO):
        self.db = db
        self.user_dao = user_dao

    # ---- Permission helper -----

    @staticmethod
    def has_permission(role: str | None, minimum: str) -> bool:
        if role is None:
            return False
        return ROLE_RANK.get(role, -1) >= ROLE_RANK.get(minimum, 99)

    def get_role(self, ledger_id: int, user_id: int) -> str | None:
        row = self.db.query_one(
            
            (ledger_id, user_id),
        )
        return row["role"] if row else None

    def _require(self, ledger_id: int, user_id: int, minimum: str):
        role = self.get_role(ledger_id, user_id)
        if not self.has_permission(role, minimum):
            raise PermissionError(
                f"You need '{minimum}' access or higher on this ledger to do that."
            )
        return role

    # ---- Ledger lifecycle ----

    def create_ledger(self, name: str, base_currency: str, owner_user_id: int) -> int:
        name = name.strip() or "Untitled Ledger"
        cur = self.db.execute(
            
            (name, base_currency.upper() or "USD", owner_user_id),
        )
        ledger_id = cur.lastrowid
        self.db.execute(
            
            (ledger_id, owner_user_id),
        )
        for cat_name, cat_type in DEFAULT_CATEGORIES:
            self.db.execute(
                
                (ledger_id, cat_name, cat_type),
            )
        return ledger_id

    def get_ledger(self, ledger_id: int):
        return self.db.query_one("SELECT * FROM Ledgers WHERE id = ?", (ledger_id,))

    def get_ledgers_for_user(self, user_id: int) -> list[dict]:
        rows = self.db.query(
            
            (user_id,),
        )
        return [dict(r) for r in rows]

    def rename_ledger(self, ledger_id: int, new_name: str, acting_user_id: int):
        self._require(ledger_id, acting_user_id, "admin")
        self.db.execute("UPDATE Ledgers SET name = ? WHERE id = ?", (new_name.strip(), ledger_id))

    def set_base_currency(self, ledger_id: int, currency: str, acting_user_id: int):
        self._require(ledger_id, acting_user_id, "admin")
        self.db.execute(
            "UPDATE Ledgers SET base_currency = ? WHERE id = ?", (currency.upper(), ledger_id)
        )

    def delete_ledger(self, ledger_id: int, acting_user_id: int):
        self._require(ledger_id, acting_user_id, "owner")
        self.db.execute("DELETE FROM Ledgers WHERE id = ?", (ledger_id,))

    # ---- Membership -----

    def list_members(self, ledger_id: int) -> list[dict]:
        rows = self.db.query(
           
            (ledger_id,),
        )
        return [dict(r) for r in rows]

    def invite_member(self, ledger_id: int, username: str, role: str, acting_user_id: int):
       
        acting_role = self._require(ledger_id, acting_user_id, "admin")
        if role not in ("admin", "editor", "viewer"):
            raise ValueError("Role must be one of: admin, editor, viewer.")
        if role == "admin" and acting_role != "owner":
            raise PermissionError("Only the ledger owner can grant admin access.")

        user = self.user_dao.get_by_username(username)
        if user is None:
            raise ValueError(f"No account found with username '{username}'.")

        existing_role = self.get_role(ledger_id, user["id"])
        if existing_role == "owner":
            raise ValueError(f"{username} already owns this ledger.")

        if existing_role:
            self.db.execute(
        
                (role, ledger_id, user["id"]),
            )
        else:
            self.db.execute(

                (ledger_id, user["id"], role),
            )

    def change_role(self, ledger_id: int, target_user_id: int, new_role: str, acting_user_id: int):
        acting_role = self._require(ledger_id, acting_user_id, "admin")
        target_role = self.get_role(ledger_id, target_user_id)
        if target_role == "owner":
            raise ValueError("The ledger owner's role can't be changed here.")
        if new_role == "admin" and acting_role != "owner":
            raise PermissionError("Only the ledger owner can grant admin access.")
        if new_role not in ("admin", "editor", "viewer"):
            raise ValueError("Role must be one of: admin, editor, viewer.")
        self.db.execute(
            
            (new_role, ledger_id, target_user_id),
        )

    def remove_member(self, ledger_id: int, target_user_id: int, acting_user_id: int):
        target_role = self.get_role(ledger_id, target_user_id)
        if target_role == "owner":
            raise ValueError("The ledger owner can't be removed. Delete the ledger instead.")
        if target_user_id != acting_user_id:
            self._require(ledger_id, acting_user_id, "admin")
        # else: anyone can remove themselves (leave the ledger)
        self.db.execute(
            
            (ledger_id, target_user_id),
        )


# CategoryDAO (ledger-scoped)

class CategoryDAO:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def get_all(self, ledger_id: int) -> list[Category]:
        rows = self.db.query(
            "SELECT * FROM Categories WHERE ledger_id = ? ORDER BY name ASC", (ledger_id,)
        )
        return [Category(r["id"], r["ledger_id"], r["name"], r["monthly_budget"], r["category_type"]) for r in rows]

    def get_by_name(self, ledger_id: int, name: str) -> Category | None:
        row = self.db.query_one(
            "SELECT * FROM Categories WHERE ledger_id = ? AND name = ?", (ledger_id, name)
        )
        return Category(row["id"], row["ledger_id"], row["name"], row["monthly_budget"], row["category_type"]) if row else None

    def add(self, ledger_id: int, name: str, monthly_budget: float = 0.0, category_type: str = "personal") -> int:
        if category_type not in ("personal", "business"):
            raise ValueError("category_type must be 'personal' or 'business'")
        cur = self.db.execute(
            
            (ledger_id, name, monthly_budget, category_type),
        )
        return cur.lastrowid

    def update_budget(self, category_id: int, monthly_budget: float):
        self.db.execute(
            
            (monthly_budget, category_id),
        )

    def update(self, category_id: int, name: str, monthly_budget: float, category_type: str):
        if category_type not in ("personal", "business"):
            raise ValueError("category_type must be 'personal' or 'business'")
        self.db.execute(
            
            (name, monthly_budget, category_type, category_id),
        )

    def delete(self, category_id: int):
        self.db.execute("DELETE FROM Categories WHERE id = ?", (category_id,))

    @staticmethod
    def budget_status(spent: float, budget: float) -> str:
        if not budget:
            return "no_budget"
        ratio = spent / budget
        if ratio >= BUDGET_OVER_THRESHOLD:
            return "over"
        if ratio >= BUDGET_WARNING_THRESHOLD:
            return "warning"
        return "ok"



# TransactionDAO (ledger-scoped)

class TransactionDAO:
    def __init__(self, db: DatabaseManager):
        self.db = db

    # ---- CRUD ----

    def add(
        self,
        ledger_id: int,
        user_id: int,
        category_id: int,
        amount: float,
        currency: str,
        description: str,
        txn_date: str,
        txn_type: str = "expense",
        rate_to_base: float = 1.0,
        base_currency: str = "USD",
        recurring_id: int | None = None,
    ) -> int:
        if txn_type not in ("income", "expense"):
            raise ValueError("txn_type must be 'income' or 'expense'")
        cur = self.db.execute(
            
            (ledger_id, user_id, category_id, amount, currency, txn_type,
             rate_to_base, base_currency, description, txn_date, recurring_id),
        )
        return cur.lastrowid

    def update(
        self,
        txn_id: int,
        category_id: int,
        amount: float,
        currency: str,
        description: str,
        txn_date: str,
        txn_type: str = "expense",
        rate_to_base: float = 1.0,
        base_currency: str = "USD",
    ):
        if txn_type not in ("income", "expense"):
            raise ValueError("txn_type must be 'income' or 'expense'")
        self.db.execute(

            (category_id, amount, currency, txn_type, rate_to_base,
             base_currency, description, txn_date, txn_id),
        )

    def delete(self, txn_id: int):
        self.db.execute("DELETE FROM Transactions WHERE id = ?", (txn_id,))

    def get_by_id(self, txn_id: int):
        return self.db.query_one("SELECT * FROM Transactions WHERE id = ?", (txn_id,))

    # ---- Filtered listing ------

    def list_transactions(
        self,
        ledger_id: int,
        category_id: int | None = None,
        month: str | None = None,  # format 'YYYY-MM'
        search_text: str | None = None,
        txn_type: str | None = None,  # 'income' | 'expense' | None (both)
    ) -> list[Transaction]:
        
        sql = """
            SELECT t.id, t.ledger_id, t.user_id, t.category_id, c.name AS category_name,
                   t.amount, t.currency, t.txn_type, t.rate_to_base,
                   t.base_currency, t.description, t.txn_date, t.recurring_id,
                   u.username AS added_by_username
            FROM Transactions t
            JOIN Categories c ON c.id = t.category_id
            LEFT JOIN Users u ON u.id = t.user_id
            WHERE t.ledger_id = ?
        """
        params: list = [ledger_id]

        if category_id:
            sql += " AND t.category_id = ?"
            params.append(category_id)

        if month:
            sql += " AND strftime('%Y-%m', t.txn_date) = ?"
            params.append(month)

        if search_text:
            sql += " AND t.description LIKE ?"
            params.append(f"%{search_text}%")

        if txn_type:
            sql += " AND t.txn_type = ?"
            params.append(txn_type)

        sql += " ORDER BY t.txn_date DESC, t.id DESC"

        rows = self.db.query(sql, tuple(params))
        return [
            Transaction(
                r["id"], r["ledger_id"], r["user_id"], r["category_id"], r["category_name"],
                r["amount"], r["currency"], r["txn_type"], r["rate_to_base"],
                r["base_currency"], r["description"], r["txn_date"], r["recurring_id"],
                r["added_by_username"] or "",
            )
            for r in rows
        ]

    # ---- Aggregations (Expenses vs Budgets) ----------

    def total_by_category_for_month(self, ledger_id: int, month: str) -> list[dict]:
        transactions = self.list_transactions(ledger_id, month=month, txn_type="expense")
        totals: dict[str, float] = {}
        for t in transactions:
            totals[t.category_name] = totals.get(t.category_name, 0.0) + t.base_amount

        categories = self.db.query(
            "SELECT name, monthly_budget FROM Categories WHERE ledger_id = ? ORDER BY name ASC",
            (ledger_id,),
        )
        return [
            {
                "category_name": c["name"],
                "monthly_budget": c["monthly_budget"],
                "total_spent": totals.get(c["name"], 0.0),
            }
            for c in categories
        ]

    def total_for_month(self, ledger_id: int, month: str, txn_type: str | None = None) -> float:
        transactions = self.list_transactions(ledger_id, month=month, txn_type=txn_type or "expense")
        return sum(t.base_amount for t in transactions)

    def monthly_totals(self, ledger_id: int, limit_months: int = 12) -> list:
        
        sql = """
            SELECT strftime('%Y-%m', txn_date) AS month,
                   txn_type, amount, rate_to_base
            FROM Transactions
            WHERE ledger_id = ?
            ORDER BY month DESC
        """
        rows = self.db.query(sql, (ledger_id,))
        totals: dict[str, float] = {}
        for r in rows:
            if r["txn_type"] != "expense":
                continue
            totals[r["month"]] = totals.get(r["month"], 0.0) + r["amount"] * r["rate_to_base"]
        months_sorted = sorted(totals.keys(), reverse=True)[:limit_months]
        return [{"month": m, "total": totals[m]} for m in months_sorted]

    # ---- Income & Expense Tracking / P&L ------

    def monthly_pl(self, ledger_id: int, month: str) -> dict:
        
        income_total = sum(
            t.base_amount for t in self.list_transactions(ledger_id, month=month, txn_type="income")
        )
        expense_total = sum(
            t.base_amount for t in self.list_transactions(ledger_id, month=month, txn_type="expense")
        )
        return {
            "income_total": income_total,
            "expense_total": expense_total,
            "net": income_total - expense_total,
        }

    # ---- Export ------

    def export_transactions_csv(
        self,
        ledger_id: int,
        category_id: int | None = None,
        month: str | None = None,
        search_text: str | None = None,
        txn_type: str | None = None,
    ) -> str:
        
        transactions = self.list_transactions(
            ledger_id, category_id=category_id, month=month,
            search_text=search_text, txn_type=txn_type,
        )
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "id", "date", "type", "category", "amount", "currency",
            "rate_to_base", "base_currency", "base_amount", "added_by",
            "description", "recurring",
        ])
        for t in transactions:
            writer.writerow([
                t.id, t.txn_date, t.txn_type, t.category_name,
                f"{t.amount:.2f}", t.currency, f"{t.rate_to_base:.6f}",
                t.base_currency, f"{t.base_amount:.2f}", t.added_by_username,
                t.description or "", "yes" if t.recurring_id else "no",
            ])
        return buf.getvalue()


# RecurringTransactionDAO -- repeating-transaction rules

class RecurringTransactionDAO:
   
    def __init__(self, db: DatabaseManager):
        self.db = db

    def add(
        self,
        ledger_id: int,
        category_id: int,
        amount: float,
        currency: str,
        txn_type: str,
        description: str,
        frequency: str,
        interval_count: int,
        start_date: str,
        end_date: str | None,
        created_by: int,
    ) -> int:
        if txn_type not in ("income", "expense"):
            raise ValueError("txn_type must be 'income' or 'expense'")
        if frequency not in ("daily", "weekly", "monthly", "yearly"):
            raise ValueError("frequency must be daily, weekly, monthly, or yearly")
        if interval_count < 1:
            raise ValueError("interval must be at least 1")
        cur = self.db.execute(
            
            (ledger_id, category_id, amount, currency, txn_type, description,
             frequency, interval_count, start_date, end_date, start_date, created_by),
        )
        return cur.lastrowid

    def update(
        self,
        rule_id: int,
        category_id: int,
        amount: float,
        currency: str,
        txn_type: str,
        description: str,
        frequency: str,
        interval_count: int,
        end_date: str | None,
    ):
        if txn_type not in ("income", "expense"):
            raise ValueError("txn_type must be 'income' or 'expense'")
        if frequency not in ("daily", "weekly", "monthly", "yearly"):
            raise ValueError("frequency must be daily, weekly, monthly, or yearly")
        self.db.execute(

            (category_id, amount, currency, txn_type, description,
             frequency, interval_count, end_date, rule_id),
        )

    def set_active(self, rule_id: int, active: bool):
        self.db.execute(
             (1 if active else 0, rule_id)
        )

    def delete(self, rule_id: int):
        self.db.execute("DELETE FROM RecurringTransactions WHERE id = ?", (rule_id,))

    def list_for_ledger(self, ledger_id: int) -> list[RecurringRule]:
        rows = self.db.query(
            
            (ledger_id,),
        )
        return [
            RecurringRule(
                r["id"], r["ledger_id"], r["category_id"], r["category_name"],
                r["amount"], r["currency"], r["txn_type"], r["description"] or "",
                r["frequency"], r["interval_count"], r["start_date"], r["end_date"],
                r["next_run_date"], bool(r["active"]),
            )
            for r in rows
        ]

    # ---- Date math -----

    @staticmethod
    def _advance(current: date, frequency: str, interval_count: int) -> date:
        if frequency == "daily":
            return current + timedelta(days=interval_count)
        if frequency == "weekly":
            return current + timedelta(weeks=interval_count)
        if frequency == "monthly":
            return RecurringTransactionDAO._add_months(current, interval_count)
        if frequency == "yearly":
            return RecurringTransactionDAO._add_months(current, interval_count * 12)
        raise ValueError(f"Unknown frequency: {frequency}")

    @staticmethod
    def _add_months(d: date, months: int) -> date:
        import calendar
        total_month_index = d.month - 1 + months
        year = d.year + total_month_index // 12
        month = total_month_index % 12 + 1
        day = min(d.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)

    # ---- Materializing due rules into real transactions --------
    
    def generate_due(
        self,
        ledger_id: int,
        txn_dao: TransactionDAO,
        currency_service,
        base_currency: str,
        acting_user_id: int,
        today: date | None = None,
    ) -> dict:
        
        from backend.currency_service import CurrencyServiceError

        today = today or date.today()
        created = 0
        skipped_rules: list[int] = []

        for rule in self.list_for_ledger(ledger_id):
            if not rule.active:
                continue
            next_run = date.fromisoformat(rule.next_run_date)
            end = date.fromisoformat(rule.end_date) if rule.end_date else None
            rule_failed = False

            while next_run <= today and (end is None or next_run <= end):
                try:
                    rate_to_base = currency_service.get_rate(rule.currency, base_currency)
                except Exception:  # noqa: BLE001 - CurrencyServiceError or network issue
                    rule_failed = True
                    break

                txn_dao.add(
                    ledger_id=ledger_id,
                    user_id=acting_user_id,
                    category_id=rule.category_id,
                    amount=rule.amount,
                    currency=rule.currency,
                    description=(rule.description or "").strip() or "(recurring)",
                    txn_date=next_run.isoformat(),
                    txn_type=rule.txn_type,
                    rate_to_base=rate_to_base,
                    base_currency=base_currency,
                    recurring_id=rule.id,
                )
                created += 1
                next_run = self._advance(next_run, rule.frequency, rule.interval_count)

            if rule_failed:
                skipped_rules.append(rule.id)
                continue

            if end is not None and next_run > end:
                self.set_active(rule.id, False)
            self.db.execute(
                "UPDATE RecurringTransactions SET next_run_date = ? WHERE id = ?",
                (next_run.isoformat(), rule.id),
            )

        return {"created": created, "skipped_rules": skipped_rules}