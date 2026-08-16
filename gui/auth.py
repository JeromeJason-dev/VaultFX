from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from backend.db import DatabaseManager
from backend.dao import UserDAO, LedgerDAO
from gui.app import PALETTE


COMMON_CURRENCIES = ["USD", "EUR", "GBP", "KES", "JPY", "INR", "CAD", "AUD", "ZAR", "NGN"]

ROLE_DESCRIPTIONS = {
    "owner": "Owner \u2014 full control",
    "admin": "Admin \u2014 manage members & settings",
    "editor": "Editor \u2014 add/edit transactions",
    "viewer": "Viewer \u2014 read only",
}


class AuthWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Sign in \u2014 Personal Finance Tracker")
        self.geometry("600x600")
        self.minsize(380, 420)
        self.configure(bg=PALETTE["bg"])

        # ---- Backend wiring -----

        self.db = DatabaseManager()
        self.user_dao = UserDAO(self.db)
        self.authenticated_user = None

        self._build_style()
        self._show_login()

    
    # Styling
    
    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        p = PALETTE
        style.configure(".", background=p["bg"], foreground=p["navy"], font=("Segoe UI", 10))
        style.configure("TFrame", background=p["bg"])
        style.configure("TLabel", background=p["bg"], foreground=p["navy"])
        style.configure("TRadiobutton", background=p["bg"])
        style.configure("TCheckbutton", background=p["bg"])
        style.configure("TEntry", fieldbackground=p["surface"], bordercolor=p["border"])
        style.configure("TCombobox", fieldbackground=p["surface"], bordercolor=p["border"])
        style.map("TCombobox", fieldbackground=[("readonly", p["surface"])])

        style.configure("AuthHeader.TLabel", background=p["bg"], foreground=p["primary_dark"],
                         font=("Segoe UI", 18, "bold"))
        style.configure("AuthSubtitle.TLabel", background=p["bg"], foreground=p["muted"])
        style.configure("AuthError.TLabel", background=p["bg"], foreground=p["coral"],
                         font=("Segoe UI", 9, "bold"))
        style.configure("AuthLink.TLabel", background=p["bg"], foreground=p["teal"],
                         font=("Segoe UI", 10, "bold", "underline"))

        style.configure("TButton", padding=8, font=("Segoe UI", 10, "bold"), borderwidth=0)
        style.configure("AuthPrimary.TButton", background=p["primary"], foreground="white")
        style.map(
            "AuthPrimary.TButton",
            background=[("active", p["primary_dark"]), ("pressed", p["primary_dark"])],
        )
        style.configure("AuthSuccess.TButton", background=p["green"], foreground="white")
        style.map(
            "AuthSuccess.TButton",
            background=[("active", "#059c66"), ("pressed", "#059c66")],
        )

    def _clear(self):
        for widget in self.winfo_children():
            widget.destroy()

    
    # Login screen
    
    def _show_login(self):
        self._clear()
        self.title("Sign in \u2014 Personal Finance Tracker")

        banner = tk.Frame(self, bg=PALETTE["primary"], height=64)
        banner.pack(fill="x")
        banner.pack_propagate(False)
        tk.Label(
            banner, text="\U0001F4B0  Finance Tracker", bg=PALETTE["primary"], fg="white",
            font=("Segoe UI", 15, "bold"),
        ).pack(pady=16)

        outer = ttk.Frame(self, padding=24)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Welcome back", style="AuthHeader.TLabel").pack(anchor="w")
        ttk.Label(
            outer, text="Sign in to your finance tracker", style="AuthSubtitle.TLabel"
        ).pack(anchor="w", pady=(0, 18))

        ttk.Label(outer, text="Username").pack(anchor="w")
        username_var = tk.StringVar()
        username_entry = ttk.Entry(outer, textvariable=username_var)
        username_entry.pack(fill="x", pady=(2, 10))

        ttk.Label(outer, text="Password").pack(anchor="w")
        password_var = tk.StringVar()
        password_entry = ttk.Entry(outer, textvariable=password_var, show="\u2022")
        password_entry.pack(fill="x", pady=(2, 4))

        error_var = tk.StringVar()
        ttk.Label(outer, textvariable=error_var, style="AuthError.TLabel", wraplength=360).pack(
            anchor="w", pady=(2, 12)
        )

        def do_login(_event=None):
            username = username_var.get().strip()
            password = password_var.get()
            if not username or not password:
                error_var.set("Enter your username and password.")
                return
            user = self.user_dao.verify_credentials(username, password)
            if user is None:
                error_var.set("Incorrect username or password.")
                return
            self.authenticated_user = user
            self.destroy()

        ttk.Button(outer, text="Sign In", style="AuthPrimary.TButton", command=do_login).pack(
            fill="x", pady=(6, 4)
        )

        switch_frame = ttk.Frame(outer)
        switch_frame.pack(fill="x", pady=(16, 0))
        ttk.Label(switch_frame, text="Don't have an account?").pack(side="left")
        register_link = ttk.Label(switch_frame, text=" Register", style="AuthLink.TLabel", cursor="hand2")
        register_link.pack(side="left")
        register_link.bind("<Button-1>", lambda _e: self._show_register())

        # Enter submits the form from either field; Tab moves between them.
        username_entry.bind("<Return>", do_login)
        password_entry.bind("<Return>", do_login)
        username_entry.focus_set()

    
    # Registration screen
    
    def _show_register(self):
        self._clear()
        self.title("Create account \u2014 Personal Finance Tracker")

        banner = tk.Frame(self, bg=PALETTE["teal"], height=64)
        banner.pack(fill="x")
        banner.pack_propagate(False)
        tk.Label(
            banner, text="\u2728  New Account", bg=PALETTE["teal"], fg="white",
            font=("Segoe UI", 15, "bold"),
        ).pack(pady=16)

        outer = ttk.Frame(self, padding=24)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Create your account", style="AuthHeader.TLabel").pack(anchor="w")
        ttk.Label(
            outer, text="Set up a new finance tracker profile", style="AuthSubtitle.TLabel"
        ).pack(anchor="w", pady=(0, 16))

        ttk.Label(outer, text="Username").pack(anchor="w")
        username_var = tk.StringVar()
        username_entry = ttk.Entry(outer, textvariable=username_var)
        username_entry.pack(fill="x", pady=(2, 10))

        ttk.Label(outer, text="Base currency").pack(anchor="w")
        currency_var = tk.StringVar(value="USD")
        ttk.Combobox(
            outer, textvariable=currency_var, values=COMMON_CURRENCIES, state="readonly", width=10
        ).pack(anchor="w", pady=(2, 10))

        ttk.Label(outer, text="Password (min. 6 characters)").pack(anchor="w")
        password_var = tk.StringVar()
        password_entry = ttk.Entry(outer, textvariable=password_var, show="\u2022")
        password_entry.pack(fill="x", pady=(2, 10))

        ttk.Label(outer, text="Confirm password").pack(anchor="w")
        confirm_var = tk.StringVar()
        confirm_entry = ttk.Entry(outer, textvariable=confirm_var, show="\u2022")
        confirm_entry.pack(fill="x", pady=(2, 4))

        error_var = tk.StringVar()
        ttk.Label(outer, textvariable=error_var, style="AuthError.TLabel", wraplength=360).pack(
            anchor="w", pady=(2, 12)
        )

        def do_register(_event=None):
            username = username_var.get().strip()
            password = password_var.get()
            confirm = confirm_var.get()
            base_currency = currency_var.get().strip().upper() or "USD"

            if password != confirm:
                error_var.set("Passwords do not match.")
                return

            try:
                self.user_dao.create_user(username, password, base_currency=base_currency)
            except ValueError as exc:
                error_var.set(str(exc))
                return

            user = self.user_dao.verify_credentials(username, password)
            self.authenticated_user = user
            messagebox.showinfo(
                "Account created", f"Welcome, {username}! You're now signed in.", parent=self
            )
            self.destroy()

        ttk.Button(outer, text="Create Account", style="AuthSuccess.TButton", command=do_register).pack(
            fill="x", pady=(6, 4)
        )

        switch_frame = ttk.Frame(outer)
        switch_frame.pack(fill="x", pady=(16, 0))
        ttk.Label(switch_frame, text="Already have an account?").pack(side="left")
        login_link = ttk.Label(switch_frame, text=" Sign in", style="AuthLink.TLabel", cursor="hand2")
        login_link.pack(side="left")
        login_link.bind("<Button-1>", lambda _e: self._show_login())

        for widget in (username_entry, password_entry, confirm_entry):
            widget.bind("<Return>", do_register)
        username_entry.focus_set()


class LedgerPickerWindow(tk.Tk):
    """Shown after login when the user belongs to more than one shared
    ledger, so they can choose which one to open (or create a new one)."""

    def __init__(self, user_dao: UserDAO, ledger_dao: LedgerDAO, user):
        super().__init__()
        self.user_dao = user_dao
        self.ledger_dao = ledger_dao
        self.user = user
        self.chosen_ledger_id: int | None = None

        self.title("Choose a Ledger \u2014 Personal Finance Tracker")
        self.geometry("600x500")
        self.minsize(420, 380)
        self.configure(bg=PALETTE["bg"])

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        p = PALETTE
        style.configure(".", background=p["bg"], foreground=p["navy"], font=("Segoe UI", 10))
        style.configure("TFrame", background=p["bg"])
        style.configure("TLabel", background=p["bg"], foreground=p["navy"])
        style.configure("PickerHeader.TLabel", background=p["bg"], foreground=p["primary_dark"],
                         font=("Segoe UI", 15, "bold"))
        style.configure("TButton", padding=8, font=("Segoe UI", 10, "bold"), borderwidth=0)
        style.configure("PickerPrimary.TButton", background=p["primary"], foreground="white")

        outer = ttk.Frame(self, padding=20)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text=f"Welcome, {user['username']}", style="PickerHeader.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Choose a shared ledger to open:").pack(anchor="w", pady=(2, 10))

        columns = ("name", "role", "currency")
        self.tree = ttk.Treeview(outer, columns=columns, show="headings", height=8)
        self.tree.heading("name", text="Ledger")
        self.tree.heading("role", text="Your role")
        self.tree.heading("currency", text="Base Currency")
        self.tree.column("name", width=200, anchor="w")
        self.tree.column("role", width=130, anchor="w")
        self.tree.column("currency", width=90, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=(0, 10))
        self.tree.bind("<Double-1>", lambda _e: self._open_selected())

        self._ledgers = self.ledger_dao.get_ledgers_for_user(user["id"])
        for ledger in self._ledgers:
            self.tree.insert(
                "", "end", iid=str(ledger["id"]),
                values=(ledger["name"], ROLE_DESCRIPTIONS.get(ledger["role"], ledger["role"]), ledger["base_currency"]),
            )
        if self._ledgers:
            self.tree.selection_set(str(self._ledgers[0]["id"]))

        btns = ttk.Frame(outer)
        btns.pack(fill="x")
        ttk.Button(btns, text="Open Ledger", style="PickerPrimary.TButton", command=self._open_selected).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(btns, text="Create New Ledger\u2026", command=self._create_new).pack(side="left")

    def _open_selected(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("No selection", "Select a ledger first.", parent=self)
            return
        self.chosen_ledger_id = int(selection[0])
        self.destroy()

    def _create_new(self):
        win = tk.Toplevel(self)
        win.title("Create New Ledger")
        win.configure(bg=PALETTE["bg"])
        win.transient(self)
        win.grab_set()

        form = ttk.Frame(win, padding=16)
        form.pack(fill="both", expand=True)

        ttk.Label(form, text="Ledger name").grid(row=0, column=0, sticky="w", pady=4)
        name_var = tk.StringVar(value=f"{self.user['username']}'s Ledger")
        ttk.Entry(form, textvariable=name_var, width=30).grid(row=0, column=1, pady=4)

        ttk.Label(form, text="Base currency").grid(row=1, column=0, sticky="w", pady=4)
        currency_var = tk.StringVar(value=self.user["base_currency"])
        ttk.Combobox(
            form, textvariable=currency_var, values=COMMON_CURRENCIES, width=10, state="readonly"
        ).grid(row=1, column=1, sticky="w", pady=4)

        def create():
            name = name_var.get().strip()
            if not name:
                messagebox.showerror("Invalid name", "Enter a ledger name.", parent=win)
                return
            ledger_id = self.ledger_dao.create_ledger(name, currency_var.get(), self.user["id"])
            self.chosen_ledger_id = ledger_id
            win.destroy()
            self.destroy()

        ttk.Button(form, text="Create", style="PickerPrimary.TButton" if False else "TButton", command=create).grid(
            row=2, column=0, columnspan=2, pady=(12, 0)
        )


def run_auth():
    """Shows the login/registration landing window, then (once someone's
    authenticated) resolves which shared ledger they're working in.

    Returns (db, user_dao, ledger_dao, user_row, ledger_row, role) on
    success, or None if no one signed in -- in which case the caller
    should exit.
    """
    auth = AuthWindow()
    auth.protocol("WM_DELETE_WINDOW", auth.destroy)
    auth.mainloop()

    if auth.authenticated_user is None:
        auth.db.close()
        return None

    db = auth.db
    user_dao = auth.user_dao
    user = auth.authenticated_user
    ledger_dao = LedgerDAO(db, user_dao)

    ledgers = ledger_dao.get_ledgers_for_user(user["id"])
    if not ledgers:
 
        ledger_id = ledger_dao.create_ledger(
            f"{user['username']}'s Ledger", user["base_currency"], user["id"]
        )
    elif len(ledgers) == 1:
        ledger_id = ledgers[0]["id"]
    else:
        picker = LedgerPickerWindow(user_dao, ledger_dao, user)
        picker.protocol("WM_DELETE_WINDOW", picker.destroy)
        picker.mainloop()
        if picker.chosen_ledger_id is None:
            db.close()
            return None
        ledger_id = picker.chosen_ledger_id

    ledger = ledger_dao.get_ledger(ledger_id)
    role = ledger_dao.get_role(ledger_id, user["id"])
    return db, user_dao, ledger_dao, user, ledger, role