"""Command-line recovery tools for operators.

    docker compose exec novel-api /app/backend/.venv/bin/python -m app.manage make-admin <username>
    docker compose exec novel-api /app/backend/.venv/bin/python -m app.manage reset-link <username>
"""

import argparse
import sys

from app import models  # noqa: F401
from app.models.user import User
from app.services import account_service
from config.database import SessionLocal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.manage")
    commands = parser.add_subparsers(dest="command", required=True)
    make_admin = commands.add_parser("make-admin", help="grant administrator rights and re-enable the account")
    make_admin.add_argument("username")
    reset_link = commands.add_parser("reset-link", help="print a one-time password reset path (valid 24 hours)")
    reset_link.add_argument("username")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == args.username).first()
        if user is None:
            print(f"No user named {args.username!r}", file=sys.stderr)
            return 1
        if args.command == "make-admin":
            user.is_admin = True
            user.is_disabled = False
            db.commit()
            print(f"{user.username} is now an administrator")
        else:
            _, token = account_service.create_password_reset(db, user, user, 24)
            print(f"/reset-password?token={token}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
