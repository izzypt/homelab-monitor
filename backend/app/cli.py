"""Operator CLI: `python -m app.cli <command>`.

create-admin --email you@example.com     prompts for the password (or reads it from stdin)
"""

import argparse
import getpass
import sys

from sqlalchemy import func, select

MIN_PASSWORD_LENGTH = 12


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords do not match.")
    return first


def create_admin(email: str, password: str) -> int:
    # Imported lazily so `--help` works without a database configured.
    from app.db import SessionLocal
    from app.models import User
    from app.security import hash_password

    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(func.lower(User.email) == email.lower()))
        if user is None:
            user = User(email=email, password_hash=hash_password(password))
            db.add(user)
            action = "created"
        else:
            user.password_hash = hash_password(password)
            action = "password updated for"
        db.commit()
        print(f"Admin {action}: {email}")
        return user.id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description="homelab-monitor admin CLI")
    sub = parser.add_subparsers(dest="command", metavar="command")
    admin = sub.add_parser("create-admin", help="create the admin user, or reset its password")
    admin.add_argument("--email", required=True)
    admin.add_argument("--password-stdin", action="store_true", help="read password from stdin")
    args = parser.parse_args(argv)

    if args.command == "create-admin":
        create_admin(args.email, _read_password(args.password_stdin))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
