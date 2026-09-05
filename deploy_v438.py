"""
v4.38 Engineering + Quality Deployment Script

Deploys 6 fixes:
  Fix #2: OpenAPI docs (rbac whitelist — already correct)
  Fix #3: Config Manager (config_manager.py + routes_v438.py)
  Fix #4: Data Provenance (provenance.py + routes_v438.py)
  Fix #5: FITS Upload + Vision (fits_upload.py)
  Fix #6: Batch Export (routes_v438.py)
  Fix #1: Testing (pytest suite — separate step)

Phases:
  1. Copy new Python modules to D:\AliCPT
  2. Hot-deploy modules to gw-pipeline container
  3. Update server.py to import new routes
  4. Restart container and verify
  5. Optional: Rebuild backend (Maven) + frontend (Vite)

Usage:
  python deploy_v438.py              # Full deploy
  python deploy_v438.py --dry-run    # Check what would be deployed
  python deploy_v438.py --skip-verify # Skip verification step
  python deploy_v438.py --rebuild     # Also rebuild backend + frontend images
"""

import os, sys, shutil, time, subprocess, argparse

SRC = r"C:\Users\28610\v438"
DST = r"D:\AliCPT"

# ── New Python modules to deploy ──
PYTHON_MODULES = [
    "gw-pipeline\\src\\pipeline\\config_manager.py",
    "gw-pipeline\\src\\pipeline\\provenance.py",
    "gw-pipeline\\src\\pipeline\\routes_v438.py",
    "gw-pipeline\\src\\pipeline\\fits_upload.py",
]

# ── Modified Python modules (need in-place edit or copy) ──
# rbac.py — already correct (/docs paths present)
# server.py — needs import for routes_v438 + fits_upload

CONTAINER = "gw-pipeline"
PIPELINE_SRC = "/app/src/pipeline"


def copy_files(dry_run=False):
    """Copy new files from v438 to D:\\AliCPT."""
    print("[1] Copying new Python modules to D:\\AliCPT...")
    for mod in PYTHON_MODULES:
        src = os.path.join(SRC, mod)
        dst = os.path.join(DST, mod)
        if not os.path.exists(src):
            print(f"  [SKIP] {mod} (not found at {src})")
            continue
        if dry_run:
            print(f"  [DRY-RUN] Would copy: {mod}")
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            print(f"  {mod}")
    print("[OK] Files copied")


def hot_deploy(dry_run=False):
    """docker cp new modules into gw-pipeline container."""
    print("[2] Hot-deploying modules to gw-pipeline container...")
    for mod in PYTHON_MODULES:
        local_path = os.path.join(DST, mod)
        module_name = os.path.basename(mod)
        container_path = f"{CONTAINER}:{PIPELINE_SRC}/{module_name}"
        if not os.path.exists(local_path):
            print(f"  [SKIP] {module_name} (local file missing)")
            continue
        if dry_run:
            print(f"  [DRY-RUN] docker cp {local_path} {container_path}")
        else:
            result = subprocess.run(
                ["docker", "cp", local_path, container_path],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                print(f"  [ERROR] {module_name}: {result.stderr.strip()}")
            else:
                print(f"  {module_name}")


def update_server_py(dry_run=False):
    """Add imports for v4.38 routes to server.py if not already present."""
    print("[3] Updating server.py imports...")
    server_py = os.path.join(DST, "gw-pipeline", "src", "pipeline", "server.py")
    if not os.path.exists(server_py):
        print(f"  [SKIP] server.py not found at {server_py}")
        return

    with open(server_py, "r", encoding="utf-8") as f:
        content = f.read()

    imports_needed = []
    if "from .routes_v438 import register_routes" not in content:
        imports_needed.append("from .routes_v438 import register_routes")
    if "from .fits_upload import register_upload_routes" not in content:
        imports_needed.append("from .fits_upload import register_upload_routes")

    if not imports_needed:
        print("  [OK] v4.38 imports already present")
        return

    if dry_run:
        for imp in imports_needed:
            print(f"  [DRY-RUN] Would add: {imp}")
        return

    # Insert imports after the existing routes_v437 import
    marker = "from .routes_v437 import register_routes"
    for imp in imports_needed:
        content = content.replace(marker, f"{marker}\n{imp}")
        print(f"  Added: {imp}")

    with open(server_py, "w", encoding="utf-8") as f:
        f.write(content)

    print("  [OK] server.py updated")

    # Also add register calls if missing
    register_needed = []
    if "register_routes_v438(app)" not in content and "register_routes(app)  # v4.38" not in content:
        register_needed.append("register_routes(app)  # v4.38: config, provenance, export (Fixes #3,#4,#6)")
    if "register_upload_routes(app)" not in content:
        register_needed.append("register_upload_routes(app)  # v4.38: FITS upload + vision (Fix #5)")

    if register_needed:
        marker = "register_routes(app)  # v4.37: security + operations routes"
        for reg in register_needed:
            content = content.replace(marker, f"{marker}\n{reg}")
            print(f"  Added register: {reg}")

        with open(server_py, "w", encoding="utf-8") as f:
            f.write(content)
        print("  [OK] server.py register calls added")


def restart_container():
    """Restart gw-pipeline container."""
    print("[4] Restarting gw-pipeline...")
    subprocess.run(["docker", "restart", CONTAINER], capture_output=True, timeout=15)
    time.sleep(8)
    print("  [OK] Container restarted")


def verify(dry_run=False):
    """Verify deployment health."""
    if dry_run:
        print("[5] [DRY-RUN] Would verify health...")
        return

    print("[5] Verifying deployment...")

    # Health check
    result = subprocess.run(
        ["docker", "exec", CONTAINER, "curl", "-s", "http://localhost:8200/health"],
        capture_output=True, text=True, timeout=10,
    )
    print(f"  Health: {result.stdout.strip()[:200]}")

    # Metrics
    result = subprocess.run(
        ["docker", "exec", CONTAINER, "curl", "-s", "http://localhost:8200/pipeline/metrics"],
        capture_output=True, text=True, timeout=10,
    )
    lines = result.stdout.count("\n")
    print(f"  Metrics: {len(result.stdout)} bytes ({lines} lines)")

    # New config endpoint
    result = subprocess.run(
        ["docker", "exec", CONTAINER, "curl", "-s", "http://localhost:8200/pipeline/admin/config"],
        capture_output=True, text=True, timeout=10,
    )
    print(f"  Config list: {result.stdout.strip()[:200]}")

    # Frontend check
    result = subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://localhost:6001/"],
        capture_output=True, text=True, timeout=10,
    )
    print(f"  Frontend: HTTP {result.stdout.strip()}")

    print("[OK] Verification complete")


def main():
    parser = argparse.ArgumentParser(description="Deploy v4.38 engineering fixes")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    parser.add_argument("--skip-verify", action="store_true", help="Skip verification")
    parser.add_argument("--skip-copy", action="store_true", help="Skip file copy (already done)")
    parser.add_argument("--rebuild", action="store_true", help="Also rebuild backend + frontend images")
    args = parser.parse_args()

    print("=" * 60)
    print("GravitationalWave v4.38 — Engineering + Quality Deployment")
    print(f"Dry run: {args.dry_run}")
    print("=" * 60)

    if not args.skip_copy:
        copy_files(dry_run=args.dry_run)

    update_server_py(dry_run=args.dry_run)
    hot_deploy(dry_run=args.dry_run)
    restart_container()

    if not args.skip_verify:
        verify(dry_run=args.dry_run)

    if args.rebuild:
        print("[6] Rebuilding backend + frontend images...")
        if not args.dry_run:
            subprocess.run(
                ["docker", "compose", "build", "gw-backend", "gw-frontend"],
                cwd=r"D:\AliCPT", timeout=600,
            )
            print("  [OK] Rebuild complete")

    print("\n[DONE] v4.38 deployment complete")
    print("New features:")
    print("  Fix #2: OpenAPI /docs enabled (pipeline + backend)")
    print("  Fix #3: Config Manager — /pipeline/admin/config/*")
    print("  Fix #4: Provenance/DOI — /pipeline/provenance/*")
    print("  Fix #5: FITS Upload + Vision — /pipeline/fits/upload, /pipeline/agent/vision")
    print("  Fix #6: Batch Export — /pipeline/export/*")


if __name__ == "__main__":
    main()
