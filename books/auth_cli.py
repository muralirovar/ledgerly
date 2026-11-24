"""Recovery from the command line, for someone who has the computer but cannot sign in.

    python -m books.auth_cli list
    python -m books.auth_cli reset USERNAME      # new temporary password, authenticator cleared, unlocked
    docker exec -it business-books python -m books.auth_cli reset USERNAME

Anyone who can run this already controls the machine and the database file, so keep the Mac locked
and turn on FileVault.
"""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

from . import access, auth, db


def main(argv: list[str]) -> int:
    path = Path(os.getenv("BOOKS_DB_PATH", Path(__file__).resolve().parent.parent / "data" / "books.db"))
    if not argv or argv[0] not in {"list", "reset"}:
        print(__doc__)
        return 2
    with db.connect(path) as connection:
        access.ensure_schema(connection)
        auth.ensure_schema(connection)
        if argv[0] == "list":
            for row in auth.list_accounts(connection):
                print(f"{row['username']:20} {'owner' if row['is_owner'] else 'editor':7} "
                      f"{'active' if row['active'] else 'off':7} mfa={'on' if row['mfa_enabled'] else 'off'}")
            return 0
        if len(argv) < 2 or not auth.get_user(connection, argv[1]):
            print("Give the username of an existing person (see: list).")
            return 1
        temp = secrets.token_urlsafe(12)
        auth.set_password(connection, argv[1], temp, must_change=True)
        auth.reset_mfa(connection, argv[1])
        auth.set_active(connection, argv[1], True)
        access.log(connection, "command line", "password reset", argv[1])
        print(f"Temporary password for {argv[1]}: {temp}\nSign in, choose a new password and set up the authenticator again.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
