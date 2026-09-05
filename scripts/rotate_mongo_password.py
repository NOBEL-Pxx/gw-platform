#!/usr/bin/env python3
"""
MongoDB Password Rotation Script — GravitationalWave Platform v4.12+

Rotates the gw-app (application) user password and updates .env.
Root admin password rotation is separate (--rotate-root).

Usage:
  python rotate_mongo_password.py              # rotate gw-app password
  python rotate_mongo_password.py --rotate-root  # rotate root admin password
  python rotate_mongo_password.py --dry-run      # preview without changes
"""

import argparse
import os
import secrets
import string
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("GW_PROJECT_DIR", r"D:\AliCPT"))
ENV_FILE = PROJECT_DIR / ".env"
ENV_EXAMPLE = PROJECT_DIR / ".env.example"

LENGTH = 24
ALPHABET = string.ascii_letters + string.digits + "%!@#$^&*()-_+=<>?"


def generate_password(length: int = LENGTH) -> str:
    """Generate a cryptographically strong random password."""
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def read_env() -> dict[str, str]:
    """Parse .env into a dict."""
    env = {}
    if ENV_FILE.exists():
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    env[key.strip()] = value.strip()
    return env


def write_env(env: dict[str, str]) -> None:
    """Write env dict back to .env file."""
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        for key, value in env.items():
            f.write(f"{key}={value}\n")
    # Also update .env.example (template, no real passwords)
    if ENV_EXAMPLE.exists():
        with open(ENV_EXAMPLE, "r", encoding="utf-8") as f:
            content = f.read()
        for key in env:
            if key in content:
                # Keep the example as is (placeholder values)
                pass


def mongosh_eval(container: str, user: str, password: str, js_cmd: str) -> bool:
    """Execute a mongosh command inside a Docker container."""
    cmd = [
        "docker", "exec", container,
        "mongosh", "-u", user, "-p", password,
        "--authenticationDatabase", "admin",
        "--quiet", "--eval", js_cmd,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr.strip()}")
        return False
    if result.stdout.strip():
        print(f"  {result.stdout.strip()}")
    return True


def rotate_app_user(env: dict, dry_run: bool) -> bool:
    """Rotate the gw-app user password."""
    current_pw = env.get("MONGO_APP_PASSWORD", "")
    if not current_pw:
        print("ERROR: MONGO_APP_PASSWORD not found in .env")
        return False

    new_pw = generate_password()
    print(f"Rotating gw-app password...")
    if dry_run:
        print(f"  DRY-RUN: would change MONGO_APP_PASSWORD to {new_pw}")
        return True

    # 1. Change password in MongoDB
    js_cmd = (
        f"db.changeUserPassword('gw-app', '{new_pw}'); "
        f"print('Password rotated for gw-app');"
    )
    print("  Updating MongoDB...")
    if not mongosh_eval("gw-mongodb", "admin", current_pw, js_cmd):
        print("  Falling back: try with root credentials...")
        root_pw = env.get("MONGO_ROOT_PASSWORD", "")
        if not mongosh_eval("gw-mongodb", "admin", root_pw, js_cmd):
            return False

    # 2. Update .env
    env["MONGO_APP_PASSWORD"] = new_pw
    write_env(env)
    print(f"  .env updated: MONGO_APP_PASSWORD={new_pw}")

    # 3. Verify new password works
    print("  Verifying new password...")
    if not mongosh_eval("gw-mongodb", "gw-app", new_pw, "db.runCommand({connectionStatus: 1}).authInfo.authenticatedUsers"):
        print("  WARNING: verification failed — restoring old password")
        mongosh_eval("gw-mongodb", "admin", new_pw,
                     f"db.changeUserPassword('gw-app', '{current_pw}');")
        env["MONGO_APP_PASSWORD"] = current_pw
        write_env(env)
        return False

    print("\n  gw-app password rotated successfully.")
    print("  Restart gw-backend to pick up new password:")
    print("    docker compose up -d --force-recreate gw-backend")
    return True


def rotate_root_user(env: dict, dry_run: bool) -> bool:
    """Rotate the root admin user password."""
    current_pw = env.get("MONGO_ROOT_PASSWORD", "")
    if not current_pw:
        print("ERROR: MONGO_ROOT_PASSWORD not found in .env")
        return False

    new_pw = generate_password()
    print(f"Rotating root admin password...")
    if dry_run:
        print(f"  DRY-RUN: would change MONGO_ROOT_PASSWORD to {new_pw}")
        return True

    # 1. Change password in MongoDB
    js_cmd = (
        f"db.changeUserPassword('admin', '{new_pw}');"
        f"print('Password rotated for admin');"
    )
    if not mongosh_eval("gw-mongodb", "admin", current_pw, js_cmd):
        return False

    # 2. Update .env and mongodb service env
    env["MONGO_ROOT_PASSWORD"] = new_pw
    write_env(env)
    print(f"  .env updated: MONGO_ROOT_PASSWORD={new_pw}")

    # 3. Verify
    if not mongosh_eval("gw-mongodb", "admin", new_pw, "db.runCommand({connectionStatus: 1}).authInfo.authenticatedUsers"):
        print("  WARNING: verification failed")
        return False

    print("\n  root admin password rotated successfully.")
    print("  Restart mongodb to pick up new password:")
    print("    docker compose up -d --force-recreate mongodb")
    print("    docker compose up -d --force-recreate gw-backend")
    return True


def main():
    parser = argparse.ArgumentParser(description="MongoDB Password Rotation — GravitationalWave Platform")
    parser.add_argument("--rotate-root", action="store_true", help="Rotate root admin password (default: rotate gw-app)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    parser.add_argument("--project-dir", default=str(PROJECT_DIR), help="Project root directory")
    args = parser.parse_args()

    global PROJECT_DIR, ENV_FILE, ENV_EXAMPLE
    PROJECT_DIR = Path(args.project_dir)
    ENV_FILE = PROJECT_DIR / ".env"
    ENV_EXAMPLE = PROJECT_DIR / ".env.example"

    if not ENV_FILE.exists():
        print(f"ERROR: .env not found at {ENV_FILE}")
        sys.exit(2)

    env = read_env()

    if args.rotate_root:
        success = rotate_root_user(env, args.dry_run)
    else:
        success = rotate_app_user(env, args.dry_run)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
