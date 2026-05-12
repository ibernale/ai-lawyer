#!/usr/bin/env python3
"""Interactive CLI to create the first admin user (or add any user).

Usage:
    python scripts/admin_bootstrap.py
    python scripts/admin_bootstrap.py --role operator --username ops1 --email ops1@example.com
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path


def _hash_password(password: str) -> str:
    try:
        import bcrypt
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    except ImportError:
        print("ERROR: bcrypt not installed. Run: pip install bcrypt", file=sys.stderr)
        sys.exit(1)


def _load_users(env_path: Path) -> list[dict]:
    """Read AUTH_USERS_JSON from .env file or environment."""
    # Try .env file first
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("AUTH_USERS_JSON="):
                raw = line.split("=", 1)[1].strip().strip("'\"")
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return []
    raw = os.getenv("AUTH_USERS_JSON", "[]")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def _save_users(env_path: Path, users: list[dict]) -> None:
    """Write updated AUTH_USERS_JSON back to .env."""
    users_json = json.dumps(users)
    if env_path.exists():
        lines = env_path.read_text().splitlines()
        new_lines = []
        replaced = False
        for line in lines:
            if line.startswith("AUTH_USERS_JSON="):
                new_lines.append(f"AUTH_USERS_JSON='{users_json}'")
                replaced = True
            else:
                new_lines.append(line)
        if not replaced:
            new_lines.append(f"AUTH_USERS_JSON='{users_json}'")
        env_path.write_text("\n".join(new_lines) + "\n")
    else:
        env_path.write_text(f"AUTH_USERS_JSON='{users_json}'\n")
    print(f"✓ Updated {env_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Add a lex-agents user")
    parser.add_argument("--username", help="Username (prompted if not given)")
    parser.add_argument("--role", default="admin", choices=["analyst", "auditor", "operator", "admin"])
    parser.add_argument("--email", help="Email (informational only)")
    parser.add_argument("--env", default=".env", help="Path to .env file")
    args = parser.parse_args()

    env_path = Path(args.env)
    users = _load_users(env_path)

    username = args.username or input("Username: ").strip()
    if not username:
        print("ERROR: username required", file=sys.stderr)
        sys.exit(1)

    if any(u["username"] == username for u in users):
        print(f"ERROR: user '{username}' already exists", file=sys.stderr)
        sys.exit(1)

    password = getpass.getpass(f"Password for {username}: ")
    if len(password) < 8:
        print("ERROR: password must be at least 8 characters", file=sys.stderr)
        sys.exit(1)

    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("ERROR: passwords do not match", file=sys.stderr)
        sys.exit(1)

    user_entry: dict = {
        "username": username,
        "password_hash": _hash_password(password),
        "role": args.role,
    }
    if args.email:
        user_entry["email"] = args.email

    users.append(user_entry)
    _save_users(env_path, users)
    print(f"✓ Added user '{username}' with role '{args.role}'")


if __name__ == "__main__":
    main()
