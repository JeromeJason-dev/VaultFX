from gui.auth import run_auth, LedgerPickerWindow
from gui.app import ExpenseTrackerApp


def run():
    while True:
        auth_result = run_auth()
        if auth_result is None:

            return

        db, user_dao, ledger_dao, user, ledger, role = auth_result

        while True:
            app = ExpenseTrackerApp(db, user_dao, ledger_dao, user, ledger, role)
            app.protocol("WM_DELETE_WINDOW", app.on_close)
            app.mainloop()

            if app.switch_ledger_requested:
                picker = LedgerPickerWindow(user_dao, ledger_dao, user)
                picker.protocol("WM_DELETE_WINDOW", picker.destroy)
                picker.mainloop()
                if picker.chosen_ledger_id is None:
                    db.close()
                    return
                ledger = ledger_dao.get_ledger(picker.chosen_ledger_id)
                role = ledger_dao.get_role(ledger["id"], user["id"])
                continue  

            if app.logout_requested:
                break  

            return

if __name__ == "__main__":
    run()
