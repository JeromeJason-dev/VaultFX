from __future__ import annotations

import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import date

from backend.db import DatabaseManager, ROLE_RANK
from backend.dao import UserDAO, CategoryDAO, TransactionDAO, LedgerDAO
from backend.currency_service import CurrencyService, CurrencyServiceError


COMMON_CURRENCIES = ["USD", "EUR", "GBP", "KES", "JPY", "INR", "CAD", "AUD", "ZAR", "NGN"]
ROLE_LABELS = {"owner": "Owner", "admin": "Admin", "editor": "Editor", "viewer": "Viewer"}

# Budget badge -> (label suffix, row tag) used by the summary panel.
BUDGET_BADGES = {
    "over": ("\u26a0 Over budget (100%+)", "budget_over"),
    "warning": ("\u26a0 80%+ of budget", "budget_warning"),
    "ok": ("\u2713 OK", "budget_ok"),
    "no_budget": ("No budget set", "budget_none"),
}

PALETTE = {
    "bg": "#f4f2fb",           
    "surface": "#ffffff",      
    "primary": "#6c5ce7",      
    "primary_dark": "#5142c4",
    "teal": "#00b8a9",
    "amber": "#ffa62b",
    "coral": "#ef476f",
    "green": "#06c17a",
    "navy": "#22223b",
    "muted": "#6b6b83",
    "income": "#0aa66e",
    "expense": "#e0455f",
    "border": "#ded9f7",
    "row_even": "#ffffff",
    "row_odd": "#f1eefc",
}

CHART_COLORS = [
    "#6c5ce7", "#00b8a9", "#ffa62b", "#ef476f", "#06c17a",
    "#118ab2", "#f4a261", "#9b5de5", "#f15bb5", "#4361ee",
]


class ExpenseTrackerApp(tk.Tk):
    def __init__(
        self,
        db: DatabaseManager,
        user_dao: UserDAO,
        ledger_dao: LedgerDAO,
        user: sqlite3.Row,
        ledger: sqlite3.Row,
        role: str,
    ):
        """The dashboard for a signed-in user working on one shared ledger.

        Args:
            db: an already-open DatabaseManager.
            user_dao: the UserDAO bound to that same db.
            ledger_dao: the LedgerDAO bound to that same db.
            user: the authenticated user's row.
            ledger: the currently-open ledger's row.
            role: the user's role on this ledger ('owner'/'admin'/'editor'/'viewer').
        """
        super().__init__()
        self.title(f"Finance Tracker \u2014 {ledger['name']} ({user['username']})")
        self.geometry("1080x780")
        self.minsize(940, 640)

        # ---- Backend wiring ------

        self.db = db
        self.user_dao = user_dao
        self.ledger_dao = ledger_dao
        self.category_dao = CategoryDAO(self.db)
        self.txn_dao = TransactionDAO(self.db)
        self.currency_service = CurrencyService()

        self.current_user = user
        self.ledger = ledger
        self.role = role
        self.selected_txn_id: int | None = None  

        self.logout_requested = False
        self.switch_ledger_requested = False

        self._build_style()
        self._build_topbar()
        self._build_form_frame()
        self._build_filter_frame()
        self._build_treeview_frame()
        self._build_summary_frame()

        self.refresh_categories()
        self.refresh_transactions()
        self.refresh_summary()
        self._apply_role_permissions()

    
    # Permissions
    
    def _can(self, minimum: str) -> bool:
        return ROLE_RANK.get(self.role, -1) >= ROLE_RANK.get(minimum, 99)

    def _apply_role_permissions(self):
        """Viewers get a read-only dashboard; editors can work with data
        but not ledger membership/settings; admins/owners get everything."""
        can_edit = self._can("editor")
        state = "normal" if can_edit else "disabled"
        for btn in (
            self.add_btn, self.update_btn, self.delete_btn,
            self.manage_categories_btn,
        ):
            btn.config(state=state)
        self.manage_members_btn.config(state="normal" if self._can("admin") else "disabled")

    
    # UI construction
    
    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        p = PALETTE
        self.configure(bg=p["bg"])

        # ---- Base widget colors ------

        style.configure(".", background=p["bg"], foreground=p["navy"], font=("Segoe UI", 10))
        style.configure("TFrame", background=p["bg"])
        style.configure("TLabel", background=p["bg"], foreground=p["navy"])
        style.configure("Header.TLabel", background=p["bg"], foreground=p["primary_dark"],
                         font=("Segoe UI", 12, "bold"))
        style.configure("Income.TLabel", background=p["bg"], foreground=p["income"],
                         font=("Segoe UI", 11, "bold"))
        style.configure("Expense.TLabel", background=p["bg"], foreground=p["expense"],
                         font=("Segoe UI", 11, "bold"))

        # ---- Cards (LabelFrames) -------

        style.configure("TLabelframe", background=p["bg"], bordercolor=p["primary"])
        style.configure("TLabelframe.Label", background=p["bg"], foreground=p["primary_dark"],
                         font=("Segoe UI", 10, "bold"))

        # ---- Inputs --------

        style.configure("TEntry", fieldbackground=p["surface"], bordercolor=p["border"])
        style.configure("TCombobox", fieldbackground=p["surface"], bordercolor=p["border"])
        style.map("TCombobox", fieldbackground=[("readonly", p["surface"])])
        style.configure("TRadiobutton", background=p["bg"], foreground=p["navy"])
        style.configure("TCheckbutton", background=p["bg"], foreground=p["navy"])

        # ---- Top bar ------

        style.configure("Topbar.TFrame", background=p["primary"])
        style.configure("Topbar.TLabel", background=p["primary"], foreground="white",
                         font=("Segoe UI", 13, "bold"))
        style.configure("TopbarRole.TLabel", background=p["primary"], foreground="#e4e1ff",
                         font=("Segoe UI", 9, "bold"))

        # ---- Colorful button styles ------

        style.configure("TButton", padding=6, font=("Segoe UI", 9, "bold"), borderwidth=0)

        def make_button_style(name, bg, fg="white", active=None):
            active = active or bg
            style.configure(f"{name}.TButton", background=bg, foreground=fg, borderwidth=0)
            style.map(
                f"{name}.TButton",
                background=[("active", active), ("pressed", active), ("disabled", "#c9c6dc")],
                foreground=[("disabled", "#8d8aa0")],
            )

        make_button_style("Success", p["green"], active="#059c66")
        make_button_style("Info", p["primary"], active=p["primary_dark"])
        make_button_style("Danger", p["coral"], active="#d43a5c")
        make_button_style("Secondary", "#9a97b3", active="#807dab")
        make_button_style("Accent", p["teal"], active="#019589")
        make_button_style("Warning", p["amber"], fg=p["navy"], active="#e8941c")

        # ---- Treeview (transactions + summary tables) ------

        style.configure("Treeview", rowheight=26, background=p["surface"],
                         fieldbackground=p["surface"], foreground=p["navy"], borderwidth=0)
        style.configure("Treeview.Heading", background=p["primary"], foreground="white",
                         font=("Segoe UI", 9, "bold"), relief="flat")
        style.map(
            "Treeview.Heading",
            background=[("active", p["primary_dark"])],
        )
        style.map(
            "Treeview",
            background=[("selected", p["teal"])],
            foreground=[("selected", "white")],
        )

    def _build_topbar(self):
        bar = ttk.Frame(self, padding=(10, 8), style="Topbar.TFrame")
        bar.pack(fill="x")

        left = ttk.Frame(bar, style="Topbar.TFrame")
        left.pack(side="left")
        ttk.Label(
            left, text=f"\U0001F4B0 {self.ledger['name']}", style="Topbar.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            left,
            text=f"Signed in as {self.current_user['username']}  \u2022  "
                 f"Role: {ROLE_LABELS.get(self.role, self.role)}",
            style="TopbarRole.TLabel",
        ).pack(anchor="w")

        right = ttk.Frame(bar, style="Topbar.TFrame")
        right.pack(side="right")
        ttk.Button(right, text="Log Out", style="Danger.TButton", command=self._log_out).pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(right, text="Switch Ledger", style="Secondary.TButton", command=self._switch_ledger).pack(
            side="right", padx=(6, 0)
        )
        self.manage_members_btn = ttk.Button(
            right, text="Manage Members\u2026", style="Accent.TButton", command=self.open_members_window
        )
        self.manage_members_btn.pack(side="right", padx=(6, 0))

    def _build_form_frame(self):
        frame = ttk.LabelFrame(self, text="Add / Edit Transaction")
        frame.pack(fill="x", padx=10, pady=(10, 5))

        # Amount

        ttk.Label(frame, text="Amount").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        self.amount_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.amount_var, width=12).grid(row=0, column=1, padx=6, pady=6)

        # Currency

        ttk.Label(frame, text="Currency").grid(row=0, column=2, padx=6, pady=6, sticky="w")
        self.currency_var = tk.StringVar(value=self.ledger["base_currency"])
        ttk.Combobox(
            frame, textvariable=self.currency_var, values=COMMON_CURRENCIES, width=8, state="readonly"
        ).grid(row=0, column=3, padx=6, pady=6)

        # Type: Income / Expense

        ttk.Label(frame, text="Type").grid(row=0, column=4, padx=6, pady=6, sticky="w")
        self.txn_type_var = tk.StringVar(value="expense")
        type_frame = ttk.Frame(frame)
        type_frame.grid(row=0, column=5, padx=6, pady=6, sticky="w")
        ttk.Radiobutton(type_frame, text="Expense", variable=self.txn_type_var, value="expense").pack(side="left")
        ttk.Radiobutton(type_frame, text="Income", variable=self.txn_type_var, value="income").pack(side="left")

        # Category

        ttk.Label(frame, text="Category").grid(row=1, column=0, padx=6, pady=6, sticky="w")
        self.category_var = tk.StringVar()
        self.category_combo = ttk.Combobox(frame, textvariable=self.category_var, width=22, state="readonly")
        self.category_combo.grid(row=1, column=1, padx=6, pady=6, columnspan=2, sticky="w")

        # Date

        ttk.Label(frame, text="Date (YYYY-MM-DD)").grid(row=1, column=3, padx=6, pady=6, sticky="w")
        self.date_var = tk.StringVar(value=date.today().isoformat())
        ttk.Entry(frame, textvariable=self.date_var, width=14).grid(row=1, column=4, padx=6, pady=6, sticky="w")

        # Description

        ttk.Label(frame, text="Description").grid(row=2, column=0, padx=6, pady=6, sticky="w")
        self.description_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.description_var, width=50).grid(
            row=2, column=1, columnspan=4, padx=6, pady=6, sticky="we"
        )

        # Buttons

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=3, column=0, columnspan=7, pady=(4, 8))

        self.add_btn = ttk.Button(btn_frame, text="Add Transaction", style="Success.TButton",
                                   command=self.add_transaction)
        self.add_btn.pack(side="left", padx=4)
        self.update_btn = ttk.Button(btn_frame, text="Update Selected", style="Info.TButton",
                                      command=self.update_transaction)
        self.update_btn.pack(side="left", padx=4)
        self.delete_btn = ttk.Button(btn_frame, text="Delete Selected", style="Danger.TButton",
                                      command=self.delete_transaction)
        self.delete_btn.pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Clear Form", style="Secondary.TButton",
                   command=self.clear_form).pack(side="left", padx=4)
        ttk.Separator(btn_frame, orient="vertical").pack(side="left", fill="y", padx=8)
        self.manage_categories_btn = ttk.Button(btn_frame, text="Manage Categories\u2026", style="Accent.TButton",
                                                 command=self.open_category_manager)
        self.manage_categories_btn.pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Reports & Export\u2026", style="Warning.TButton",
                   command=self.open_reports_window).pack(side="left", padx=4)

    def _build_filter_frame(self):
        frame = ttk.LabelFrame(self, text="Filter & Convert")
        frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame, text="Category").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        self.filter_category_var = tk.StringVar(value="All")
        self.filter_category_combo = ttk.Combobox(
            frame, textvariable=self.filter_category_var, width=16, state="readonly"
        )
        self.filter_category_combo.grid(row=0, column=1, padx=6, pady=6)

        ttk.Label(frame, text="Type").grid(row=0, column=2, padx=6, pady=6, sticky="w")
        self.filter_type_var = tk.StringVar(value="All")
        ttk.Combobox(
            frame, textvariable=self.filter_type_var, values=["All", "income", "expense"],
            width=8, state="readonly"
        ).grid(row=0, column=3, padx=6, pady=6)

        ttk.Label(frame, text="Month (YYYY-MM)").grid(row=0, column=4, padx=6, pady=6, sticky="w")
        self.filter_month_var = tk.StringVar(value=date.today().strftime("%Y-%m"))
        ttk.Entry(frame, textvariable=self.filter_month_var, width=10).grid(row=0, column=5, padx=6, pady=6)

        ttk.Label(frame, text="Search").grid(row=0, column=6, padx=6, pady=6, sticky="w")
        self.search_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.search_var, width=16).grid(row=0, column=7, padx=6, pady=6)

        ttk.Button(frame, text="Apply Filters", style="Info.TButton", command=self._apply_filters).grid(
            row=0, column=8, padx=6, pady=6
        )
        ttk.Button(frame, text="Clear Filters", style="Secondary.TButton", command=self.clear_filters).grid(
            row=0, column=9, padx=6, pady=6
        )

        # Row 2: base currency + display currency
        ttk.Label(frame, text="Base currency").grid(row=1, column=0, padx=6, pady=6, sticky="w")
        self.base_currency_var = tk.StringVar(value=self.ledger["base_currency"])
        ttk.Combobox(
            frame, textvariable=self.base_currency_var, values=COMMON_CURRENCIES, width=8, state="readonly"
        ).grid(row=1, column=1, padx=6, pady=6)
        self.save_base_currency_btn = ttk.Button(
            frame, text="Save Base Currency", style="Accent.TButton", command=self.save_base_currency
        )
        self.save_base_currency_btn.grid(row=1, column=2, columnspan=2, padx=6, pady=6, sticky="w")

        ttk.Label(frame, text="Show totals in").grid(row=1, column=4, padx=(6, 6), pady=6, sticky="w")
        self.display_currency_var = tk.StringVar(value=self.base_currency_var.get())
        ttk.Combobox(
            frame, textvariable=self.display_currency_var, values=COMMON_CURRENCIES, width=8, state="readonly"
        ).grid(row=1, column=5, padx=6, pady=6)
        ttk.Button(frame, text="Refresh Rates", style="Info.TButton",
                   command=self.refresh_summary).grid(row=1, column=6, padx=6)

    def _build_treeview_frame(self):
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=10, pady=5)

        columns = ("id", "date", "type", "category", "amount", "currency", "base_amount", "added_by", "description")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", height=12)
        headings = {
            "id": "ID", "date": "Date", "type": "Type", "category": "Category",
            "amount": "Amount", "currency": "Cur.", "base_amount": "In Base Cur.",
            "added_by": "Added By", "description": "Description",
        }
        widths = {
            "id": 36, "date": 88, "type": 64, "category": 140, "amount": 90,
            "currency": 55, "base_amount": 110, "added_by": 110, "description": 230,
        }
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w")

        self.tree.tag_configure("income", foreground=PALETTE["income"])
        self.tree.tag_configure("expense", foreground=PALETTE["expense"])
        # Zebra-striped rows for readability -- background only, layered
        # underneath the income/expense foreground color tag above.
        self.tree.tag_configure("row_even", background=PALETTE["row_even"])
        self.tree.tag_configure("row_odd", background=PALETTE["row_odd"])

        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", self.on_row_select)

    def _build_summary_frame(self):
        frame = ttk.LabelFrame(self, text="Monthly Summary (per category, converted, with budget alerts)")
        frame.pack(fill="both", expand=False, padx=10, pady=(5, 10))

        columns = ("category", "spent", "budget", "status")
        self.summary_tree = ttk.Treeview(frame, columns=columns, show="headings", height=6)
        headings = {"category": "Category", "spent": "Spent", "budget": "Budget", "status": "Status"}
        widths = {"category": 180, "spent": 120, "budget": 120, "status": 200}
        for col in columns:
            self.summary_tree.heading(col, text=headings[col])
            self.summary_tree.column(col, width=widths[col], anchor="w")
        self.summary_tree.tag_configure("budget_over", background="#fbd4dc", foreground="#8a1f3d")
        self.summary_tree.tag_configure("budget_warning", background="#ffe8bf", foreground="#8a5a00")
        self.summary_tree.tag_configure("budget_ok", background="#c9f3e2", foreground="#0a6b4a")
        self.summary_tree.tag_configure("budget_none", background=PALETTE["surface"])
        self.summary_tree.pack(fill="both", expand=True, padx=6, pady=6)

        totals_frame = ttk.Frame(frame)
        totals_frame.pack(fill="x", padx=6, pady=(0, 6))
        self.total_label = ttk.Label(
            totals_frame, text="Expenses this month: --",
            foreground=PALETTE["expense"], font=("Segoe UI", 11, "bold"),
        )
        self.total_label.pack(anchor="w")
        self.pl_label = ttk.Label(
            totals_frame, text="Income: --   Expenses: --   Net: --", style="Header.TLabel"
        )
        self.pl_label.pack(anchor="w")

    
    # Data refresh helpers
    
    def refresh_categories(self):
        categories = self.category_dao.get_all(self.ledger["id"])
        names = [c.name for c in categories]
        self.category_combo["values"] = names
        if names:
            self.category_combo.current(0)
        self.filter_category_combo["values"] = ["All"] + names
        self.filter_category_combo.current(0)

    def _apply_filters(self):
        self.refresh_transactions()
        self.refresh_summary()

    def refresh_transactions(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

        category_id = None
        if self.filter_category_var.get() != "All":
            cat = self.category_dao.get_by_name(self.ledger["id"], self.filter_category_var.get())
            category_id = cat.id if cat else None

        month = self.filter_month_var.get().strip() or None
        search = self.search_var.get().strip() or None
        txn_type = None if self.filter_type_var.get() == "All" else self.filter_type_var.get()

        transactions = self.txn_dao.list_transactions(
            ledger_id=self.ledger["id"],
            category_id=category_id,
            month=month,
            search_text=search,
            txn_type=txn_type,
        )
        for i, t in enumerate(transactions):
            stripe = "row_even" if i % 2 == 0 else "row_odd"
            self.tree.insert(
                "", "end", iid=str(t.id), tags=(t.txn_type, stripe),
                values=(
                    t.id, t.txn_date, t.txn_type, t.category_name,
                    f"{t.amount:.2f}", t.currency,
                    f"{t.base_amount:.2f} {t.base_currency}",
                    t.added_by_username,
                    t.description or "",
                ),
            )

    def refresh_summary(self):
        month = self.filter_month_var.get().strip() or date.today().strftime("%Y-%m")
        display_currency = self.display_currency_var.get() or "USD"
        base_currency = self.ledger["base_currency"]

        for row in self.summary_tree.get_children():
            self.summary_tree.delete(row)

        display_rate = 1.0
        if display_currency != base_currency:
            try:
                display_rate = self.currency_service.get_rate(base_currency, display_currency)
            except CurrencyServiceError as exc:
                messagebox.showwarning(
                    "Currency conversion",
                    f"Couldn't reach the live exchange-rate API to convert to "
                    f"{display_currency}: {exc}\n\nShowing totals in {base_currency} instead."
                )
                display_currency = base_currency  # fall back to showing base-currency figures

        rows = self.txn_dao.total_by_category_for_month(self.ledger["id"], month)
        grand_total = 0.0

        for r in rows:
            spent = r["total_spent"] * display_rate
            budget = r["monthly_budget"] * display_rate if r["monthly_budget"] else r["monthly_budget"]

            grand_total += spent
            status = CategoryDAO.budget_status(spent, budget)
            label, tag = BUDGET_BADGES[status]
            self.summary_tree.insert(
                "", "end", tags=(tag,),
                values=(r["category_name"], f"{spent:.2f} {display_currency}",
                        f"{budget:.2f} {display_currency}" if budget else "--", label),
            )

        self.total_label.config(text=f"Expenses this month: {grand_total:.2f} {display_currency}")

        # Profit & Loss (Income & Expense Tracking)
        pl = self.txn_dao.monthly_pl(self.ledger["id"], month)
        income = pl["income_total"] * display_rate
        expense = pl["expense_total"] * display_rate
        net = pl["net"] * display_rate
        self.pl_label.config(
            text=f"Income: {income:.2f} {display_currency}   "
                 f"Expenses: {expense:.2f} {display_currency}   "
                 f"Net: {net:.2f} {display_currency}"
        )

    def save_base_currency(self):
        if not self._can("admin"):
            messagebox.showinfo("Not allowed", "Only ledger admins/owners can change the base currency.")
            return
        new_base = self.base_currency_var.get().strip().upper()
        if not new_base:
            return
        try:
            self.ledger_dao.set_base_currency(self.ledger["id"], new_base, self.current_user["id"])
        except PermissionError as exc:
            messagebox.showerror("Not allowed", str(exc))
            return
        self.ledger = self.ledger_dao.get_ledger(self.ledger["id"])
        self.display_currency_var.set(new_base)
        messagebox.showinfo(
            "Base currency updated",
            f"Base currency is now {new_base}.\n\n"
            "Existing transactions keep their originally locked exchange "
            "rate (historical rate locking) -- their audited value never "
            "changes. New transactions will lock rates against the new "
            "base currency.",
        )
        self.refresh_summary()

    
    # Event handlers
    
    def add_transaction(self):
        if not self._can("editor"):
            messagebox.showinfo("Not allowed", "You have read-only (viewer) access to this ledger.")
            return
        data = self._read_form()
        if data is None:
            return
        self.txn_dao.add(
            ledger_id=self.ledger["id"],
            user_id=self.current_user["id"],
            category_id=data["category_id"],
            amount=data["amount"],
            currency=data["currency"],
            description=data["description"],
            txn_date=data["txn_date"],
            txn_type=data["txn_type"],
            rate_to_base=data["rate_to_base"],
            base_currency=data["base_currency"],
        )
        self.clear_form()
        self.refresh_transactions()
        self.refresh_summary()

    def update_transaction(self):
        if not self._can("editor"):
            messagebox.showinfo("Not allowed", "You have read-only (viewer) access to this ledger.")
            return
        if self.selected_txn_id is None:
            messagebox.showinfo("No selection", "Select a transaction in the table first.")
            return
        data = self._read_form()
        if data is None:
            return
        self.txn_dao.update(
            txn_id=self.selected_txn_id,
            category_id=data["category_id"],
            amount=data["amount"],
            currency=data["currency"],
            description=data["description"],
            txn_date=data["txn_date"],
            txn_type=data["txn_type"],
            rate_to_base=data["rate_to_base"],
            base_currency=data["base_currency"],
        )
        self.clear_form()
        self.refresh_transactions()
        self.refresh_summary()

    def delete_transaction(self):
        if not self._can("editor"):
            messagebox.showinfo("Not allowed", "You have read-only (viewer) access to this ledger.")
            return
        if self.selected_txn_id is None:
            messagebox.showinfo("No selection", "Select a transaction in the table first.")
            return
        if messagebox.askyesno("Confirm delete", "Delete the selected transaction?"):
            self.txn_dao.delete(self.selected_txn_id)
            self.clear_form()
            self.refresh_transactions()
            self.refresh_summary()

    def on_row_select(self, _event):
        selection = self.tree.selection()
        if not selection:
            return
        txn_id = int(selection[0])
        row = self.txn_dao.get_by_id(txn_id)
        if not row:
            return
        self.selected_txn_id = txn_id
        self.amount_var.set(str(row["amount"]))
        self.currency_var.set(row["currency"])
        self.txn_type_var.set(row["txn_type"])
        self.date_var.set(row["txn_date"])
        self.description_var.set(row["description"] or "")
        cat = self.db.query_one("SELECT name FROM Categories WHERE id = ?", (row["category_id"],))
        if cat:
            self.category_var.set(cat["name"])

    def clear_form(self):
        self.selected_txn_id = None
        self.amount_var.set("")
        self.description_var.set("")
        self.txn_type_var.set("expense")
        self.date_var.set(date.today().isoformat())
        if self.category_combo["values"]:
            self.category_combo.current(0)
        for row in self.tree.selection():
            self.tree.selection_remove(row)

    def clear_filters(self):
        self.filter_category_var.set("All")
        self.filter_type_var.set("All")
        self.filter_month_var.set(date.today().strftime("%Y-%m"))
        self.search_var.set("")
        self.refresh_transactions()
        self.refresh_summary()

    
    # Validation
    
    def _read_form(self) -> dict | None:
        try:
            amount = float(self.amount_var.get())
            if amount <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid amount", "Enter a positive number for amount.")
            return None

        currency = self.currency_var.get().strip().upper()
        if not currency:
            messagebox.showerror("Invalid currency", "Select a currency.")
            return None

        txn_type = self.txn_type_var.get()
        if txn_type not in ("income", "expense"):
            messagebox.showerror("Invalid type", "Select Income or Expense.")
            return None

        category_name = self.category_var.get().strip()
        category = self.category_dao.get_by_name(self.ledger["id"], category_name)
        if not category:
            messagebox.showerror("Invalid category", "Select a valid category.")
            return None

        txn_date = self.date_var.get().strip()
        try:
            date.fromisoformat(txn_date)
        except ValueError:
            messagebox.showerror("Invalid date", "Use YYYY-MM-DD format.")
            return None
        
        base_currency = self.ledger["base_currency"]
        try:
            rate_to_base = self.currency_service.get_rate(currency, base_currency)
        except CurrencyServiceError as exc:
            messagebox.showerror(
                "No internet connection",
                f"Couldn't reach the live exchange-rate API to convert "
                f"{currency} -> {base_currency} ({exc}).\n\n"
                "This app requires an internet connection to record "
                "transactions, since the exchange rate is locked in live "
                "at entry time. Please check your connection and try again.",
            )
            return None

        return {
            "amount": amount,
            "currency": currency,
            "txn_type": txn_type,
            "category_id": category.id,
            "description": self.description_var.get().strip(),
            "txn_date": txn_date,
            "rate_to_base": rate_to_base,
            "base_currency": base_currency,
        }

    
    # Category management (Custom Categories: personal + business tags)
    
    def open_category_manager(self):
        if not self._can("editor"):
            messagebox.showinfo("Not allowed", "You have read-only (viewer) access to this ledger.")
            return
        win = tk.Toplevel(self)
        win.title("Manage Categories")
        win.geometry("700x600")
        win.configure(bg=PALETTE["bg"])
        win.transient(self)

        columns = ("id", "name", "type", "budget")
        tree = ttk.Treeview(win, columns=columns, show="headings", height=10)
        for col, text, width in [
            ("id", "ID", 40), ("name", "Name", 200), ("type", "Type", 90), ("budget", "Monthly Budget", 130)
        ]:
            tree.heading(col, text=text)
            tree.column(col, width=width, anchor="w")
        tree.pack(fill="both", expand=True, padx=10, pady=(10, 6))

        def load_rows():
            for row in tree.get_children():
                tree.delete(row)
            for c in self.category_dao.get_all(self.ledger["id"]):
                tree.insert("", "end", iid=str(c.id), values=(c.id, c.name, c.category_type, f"{c.monthly_budget:.2f}"))

        form = ttk.Frame(win)
        form.pack(fill="x", padx=10, pady=6)

        ttk.Label(form, text="Name").grid(row=0, column=0, padx=4, pady=4, sticky="w")
        name_var = tk.StringVar()
        ttk.Entry(form, textvariable=name_var, width=22).grid(row=0, column=1, padx=4, pady=4)

        ttk.Label(form, text="Type").grid(row=0, column=2, padx=4, pady=4, sticky="w")
        type_var = tk.StringVar(value="personal")
        ttk.Combobox(form, textvariable=type_var, values=["personal", "business"], width=10, state="readonly").grid(
            row=0, column=3, padx=4, pady=4
        )

        ttk.Label(form, text="Monthly Budget").grid(row=0, column=4, padx=4, pady=4, sticky="w")
        budget_var = tk.StringVar(value="0")
        ttk.Entry(form, textvariable=budget_var, width=10).grid(row=0, column=5, padx=4, pady=4)

        selected_id = {"value": None}

        def on_select(_event):
            sel = tree.selection()
            if not sel:
                return
            cat_id = int(sel[0])
            row = tree.item(sel[0])["values"]
            selected_id["value"] = cat_id
            name_var.set(row[1])
            type_var.set(row[2])
            budget_var.set(row[3])

        tree.bind("<<TreeviewSelect>>", on_select)

        def read_category_form():
            name = name_var.get().strip()
            if not name:
                messagebox.showerror("Invalid name", "Enter a category name.", parent=win)
                return None
            try:
                budget = float(budget_var.get())
                if budget < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Invalid budget", "Budget must be a non-negative number.", parent=win)
                return None
            return name, budget, type_var.get()

        def add_category():
            data = read_category_form()
            if data is None:
                return
            name, budget, category_type = data
            try:
                self.category_dao.add(self.ledger["id"], name, budget, category_type)
            except sqlite3.IntegrityError:
                messagebox.showerror(
                    "Could not add category",
                    f"A category named '{name}' already exists.",
                    parent=win,
                )
                return
            except Exception as exc:  # noqa: BLE001 - surface any other DB error to the user
                messagebox.showerror("Could not add category", str(exc), parent=win)
                return
            load_rows()
            self.refresh_categories()
            self.refresh_summary()

        def update_category():
            if selected_id["value"] is None:
                messagebox.showinfo("No selection", "Select a category in the table first.", parent=win)
                return
            data = read_category_form()
            if data is None:
                return
            name, budget, category_type = data
            self.category_dao.update(selected_id["value"], name, budget, category_type)
            load_rows()
            self.refresh_categories()
            self.refresh_summary()

        def delete_category():
            if selected_id["value"] is None:
                messagebox.showinfo("No selection", "Select a category in the table first.", parent=win)
                return
            if messagebox.askyesno("Confirm delete", "Delete the selected category? "
                                    "(This will fail if transactions still reference it.)", parent=win):
                try:
                    self.category_dao.delete(selected_id["value"])
                except Exception as exc:  # noqa: BLE001
                    messagebox.showerror("Could not delete category", str(exc), parent=win)
                    return
                selected_id["value"] = None
                load_rows()
                self.refresh_categories()
                self.refresh_summary()

        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btn_frame, text="Add", style="Success.TButton", command=add_category).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Update Selected", style="Info.TButton",
                   command=update_category).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Delete Selected", style="Danger.TButton",
                   command=delete_category).pack(side="left", padx=4)

        load_rows()

    
    # Ledger membership (Role-Based Multi-User Access)
    
    def open_members_window(self):
        if not self._can("admin"):
            messagebox.showinfo("Not allowed", "Only ledger admins/owners can manage members.")
            return
        win = tk.Toplevel(self)
        win.title(f"Manage Members \u2014 {self.ledger['name']}")
        win.geometry("700x600")
        win.configure(bg=PALETTE["bg"])
        win.transient(self)

        columns = ("username", "role", "joined")
        tree = ttk.Treeview(win, columns=columns, show="headings", height=10)
        tree.heading("username", text="Username")
        tree.heading("role", text="Role")
        tree.heading("joined", text="Joined")
        tree.column("username", width=180, anchor="w")
        tree.column("role", width=100, anchor="w")
        tree.column("joined", width=160, anchor="w")
        tree.pack(fill="both", expand=True, padx=10, pady=(10, 6))

        def load_rows():
            for row in tree.get_children():
                tree.delete(row)
            for m in self.ledger_dao.list_members(self.ledger["id"]):
                tree.insert("", "end", iid=str(m["user_id"]), values=(m["username"], m["role"], m["joined_at"]))

        form = ttk.LabelFrame(win, text="Invite a Member")
        form.pack(fill="x", padx=10, pady=6)
        ttk.Label(form, text="Username").grid(row=0, column=0, padx=4, pady=6, sticky="w")
        username_var = tk.StringVar()
        ttk.Entry(form, textvariable=username_var, width=20).grid(row=0, column=1, padx=4, pady=6)
        ttk.Label(form, text="Role").grid(row=0, column=2, padx=4, pady=6, sticky="w")
        role_var = tk.StringVar(value="editor")
        ttk.Combobox(form, textvariable=role_var, values=["admin", "editor", "viewer"], width=10, state="readonly").grid(
            row=0, column=3, padx=4, pady=6
        )

        def invite():
            username = username_var.get().strip()
            if not username:
                messagebox.showerror("Invalid username", "Enter a username.", parent=win)
                return
            try:
                self.ledger_dao.invite_member(self.ledger["id"], username, role_var.get(), self.current_user["id"])
            except (ValueError, PermissionError) as exc:
                messagebox.showerror("Couldn't add member", str(exc), parent=win)
                return
            username_var.set("")
            load_rows()

        ttk.Button(form, text="Invite / Update Role", style="Success.TButton", command=invite).grid(
            row=0, column=4, padx=8, pady=6
        )

        selected_user = {"value": None}

        def on_select(_event):
            sel = tree.selection()
            selected_user["value"] = int(sel[0]) if sel else None

        tree.bind("<<TreeviewSelect>>", on_select)

        def change_role(new_role):
            if selected_user["value"] is None:
                messagebox.showinfo("No selection", "Select a member in the table first.", parent=win)
                return
            try:
                self.ledger_dao.change_role(self.ledger["id"], selected_user["value"], new_role, self.current_user["id"])
            except (ValueError, PermissionError) as exc:
                messagebox.showerror("Couldn't change role", str(exc), parent=win)
                return
            load_rows()

        def remove_member():
            if selected_user["value"] is None:
                messagebox.showinfo("No selection", "Select a member in the table first.", parent=win)
                return
            if not messagebox.askyesno("Confirm removal", "Remove this member from the ledger?", parent=win):
                return
            try:
                self.ledger_dao.remove_member(self.ledger["id"], selected_user["value"], self.current_user["id"])
            except (ValueError, PermissionError) as exc:
                messagebox.showerror("Couldn't remove member", str(exc), parent=win)
                return
            load_rows()

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btns, text="Make Admin", style="Info.TButton", command=lambda: change_role("admin")).pack(
            side="left", padx=4
        )
        ttk.Button(btns, text="Make Editor", style="Accent.TButton", command=lambda: change_role("editor")).pack(
            side="left", padx=4
        )
        ttk.Button(btns, text="Make Viewer", style="Secondary.TButton", command=lambda: change_role("viewer")).pack(
            side="left", padx=4
        )
        ttk.Button(btns, text="Remove Member", style="Danger.TButton", command=remove_member).pack(side="left", padx=4)

        load_rows()

    
    # Reports & Export (Financial Reports & Exports)
    
    def open_reports_window(self):
        win = tk.Toplevel(self)
        win.title("Reports & Export")
        win.geometry("700x600")
        win.configure(bg=PALETTE["bg"])
        win.transient(self)

        top = ttk.Frame(win)
        top.pack(fill="x", padx=10, pady=10)
        ttk.Label(top, text="Month (YYYY-MM)").pack(side="left", padx=(0, 6))
        month_var = tk.StringVar(value=self.filter_month_var.get() or date.today().strftime("%Y-%m"))
        ttk.Entry(top, textvariable=month_var, width=10).pack(side="left", padx=(0, 12))
        ttk.Label(top, text="Currency").pack(side="left", padx=(0, 6))
        currency_var = tk.StringVar(value=self.display_currency_var.get())
        ttk.Combobox(top, textvariable=currency_var, values=COMMON_CURRENCIES, width=8, state="readonly").pack(
            side="left", padx=(0, 12)
        )

        pl_label = ttk.Label(win, text="", style="Header.TLabel")
        pl_label.pack(anchor="w", padx=10, pady=(0, 6))

        chart_canvas = tk.Canvas(win, width=600, height=260, bg=PALETTE["surface"], highlightthickness=1,
                                  highlightbackground=PALETTE["border"])
        chart_canvas.pack(padx=10, pady=6)

        def base_to_display(amount, base_currency, display_currency):
            if not amount or base_currency == display_currency:
                return amount
            try:
                rate = self.currency_service.get_rate(base_currency, display_currency)
                return amount * rate
            except CurrencyServiceError as exc:
                messagebox.showwarning(
                    "Currency conversion",
                    f"Couldn't reach the live exchange-rate API to convert to "
                    f"{display_currency}: {exc}\n\nShowing this report in {base_currency} instead.",
                    parent=win,
                )
                return amount  

        def render():
            month = month_var.get().strip() or date.today().strftime("%Y-%m")
            display_currency = currency_var.get() or "USD"
            base_currency = self.ledger["base_currency"]

            pl = self.txn_dao.monthly_pl(self.ledger["id"], month)
            income = base_to_display(pl["income_total"], base_currency, display_currency)
            expense = base_to_display(pl["expense_total"], base_currency, display_currency)
            net = income - expense
            pl_label.config(
                text=f"{month} P&L \u2014 Income: {income:.2f} {display_currency}   "
                     f"Expenses: {expense:.2f} {display_currency}   "
                     f"Net: {net:.2f} {display_currency}"
            )

            rows = self.txn_dao.total_by_category_for_month(self.ledger["id"], month)
            bars = [
                (r["category_name"], base_to_display(r["total_spent"], base_currency, display_currency))
                for r in rows if r["total_spent"]
            ]

            chart_canvas.delete("all")
            if not bars:
                chart_canvas.create_text(300, 130, text="No expenses recorded for this month.")
                return

            max_val = max(v for _, v in bars) or 1
            bar_height = 22
            gap = 10
            left_margin = 160
            chart_width = 600 - left_margin - 60
            y = 15
            for idx, (name, value) in enumerate(bars):
                bar_len = (value / max_val) * chart_width
                bar_color = CHART_COLORS[idx % len(CHART_COLORS)]
                chart_canvas.create_text(
                    left_margin - 8, y + bar_height / 2, text=name, anchor="e",
                    fill=PALETTE["navy"], font=("Segoe UI", 9, "bold"),
                )
                chart_canvas.create_rectangle(
                    left_margin, y, left_margin + bar_len, y + bar_height,
                    fill=bar_color, outline=""
                )
                chart_canvas.create_text(
                    left_margin + bar_len + 6, y + bar_height / 2,
                    text=f"{value:.2f}", anchor="w", fill=PALETTE["navy"],
                )
                y += bar_height + gap
            chart_canvas.config(height=max(260, y + 15))

        def export_csv():
            month = month_var.get().strip() or None
            csv_text = self.txn_dao.export_transactions_csv(self.ledger["id"], month=month)
            path = filedialog.asksaveasfilename(
                parent=win, defaultextension=".csv",
                initialfile=f"transactions_{month or 'all'}.csv",
                filetypes=[("CSV files", "*.csv")],
            )
            if not path:
                return
            try:
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(csv_text)
            except OSError as exc:
                messagebox.showerror("Export failed", str(exc), parent=win)
                return
            messagebox.showinfo("Export complete", f"Transactions exported to:\n{path}", parent=win)

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btns, text="Refresh Report", style="Info.TButton", command=render).pack(side="left", padx=4)
        ttk.Button(btns, text="Export Filtered CSV\u2026", style="Accent.TButton",
                   command=export_csv).pack(side="left", padx=4)

        render()

    def on_close(self):
        self.db.close()
        self.destroy()

    def _log_out(self):
        if not messagebox.askyesno("Log out", "Log out of the finance tracker?", parent=self):
            return
        self.logout_requested = True
        self.db.close()
        self.destroy()

    def _switch_ledger(self):
        self.switch_ledger_requested = True
        self.destroy()