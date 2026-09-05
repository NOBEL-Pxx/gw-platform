#!/usr/bin/env python3
"""
JWT Secret Rotation — GravitationalWave Platform v4.12

Generates a new random JWT signing secret and updates .env.
Existing tokens signed with the old secret will become invalid immediately.
This is by design — a compromised key requires immediate invalidation.

Usage:
  python scripts/rotate_jwt_secret.py             # rotate secret
  python scripts/rotate_jwt_secret.py --dry-run   # preview only
  python scripts/rotate_jwt_secret.py --restart   # rotate + restart backend
"""

import argparse
import os
import secrets
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("GW_PROJECT_DIR", r"D:\AliCPT"))
ENV_FILE = PROJECT_DIR / ".env"

def generate_secret() -> str:
    """64-char hex string = 256 bits of entropy."""
    return secrets.token_hex(32)

def read_env() -> dict[str, str]:
    env = {}
    if ENV_FILE.exists():
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip()
    return env

def write_env(env: dict[str, str]) -> None:
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        for key, value in env.items():
            f.write(f"{key}={value}\n")

def main():
    parser = argparse.ArgumentParser(description="JWT Secret Rotation")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--restart", action="store_true", help="Restart gw-backend after rotation")
    args = parser.parse_args()

    env = read_env()
    old_secret = env.get("JWT_SECRET", "(not set)")
    new_secret = generate_secret()

    print(f"Old secret: {old_secret[:16]}..." if len(old_secret) > 16 else f"Old secret: {old_secret}")
    print(f"New secret: {new_secret[:16]}...")

    if args.dry_run:
        print("DRY RUN — no changes made")
        return

    env["JWT_SECRET"] = new_secret
    write_env(env)
    print(".env updated: JWT_SECRET rotated")
    print("WARNING: All existing tokens are now invalid — users must re-login.")

    if args.restart:
        print("Restarting gw-backend...")
        subprocess.run(["docker", "compose", "up", "-d", "--force-recreate", "gw-backend"],
                       cwd=str(PROJECT_DIR), check=True)
        print("Backend restarted with new JWT secret.")

if __name__ == "__main__":
    main()
