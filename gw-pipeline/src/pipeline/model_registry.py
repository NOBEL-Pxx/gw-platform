# -*- coding: utf-8 -*-
"""
Model Version Registry (v4.27)
==============================
Manages multiple model versions under /app/models/ with atomic symlink
switching. Provides version listing, activation, and rollback.

Directory structure:
  /app/models/
  ├── current -> v1/          # symlink to active version
  ├── registry.json           # version metadata + activation history
  ├── v1/
  │   ├── zoobot_encoder_greyscale.onnx
  │   ├── source_classifier.onnx
  │   └── anomaly_autoencoder.onnx
  └── v2/
      └── source_classifier_v2.onnx

Usage:
  from .model_registry import (
      init_registry,
      list_versions,
      activate_version,
      rollback_version,
      get_current_version,
  )
"""

import json
import os
import time
from pathlib import Path
from typing import Optional

_MODEL_BASE = Path(os.environ.get("DL_MODEL_DIR", "/app/models"))
_REGISTRY_PATH = _MODEL_BASE / "model_registry.json"
_CURRENT_LINK = _MODEL_BASE / "current"


def _read_registry() -> dict:
    """Read registry.json, return empty dict if missing."""
    if not _REGISTRY_PATH.exists():
        return {
            "versions": {},
            "activation_history": [],
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    try:
        with open(_REGISTRY_PATH) as f:
            return json.load(f)
    except Exception:
        return {"versions": {}, "activation_history": [], "error": "registry corrupted"}


def _write_registry(registry: dict) -> None:
    """Atomically write registry.json."""
    _MODEL_BASE.mkdir(parents=True, exist_ok=True)
    tmp_path = _REGISTRY_PATH.with_suffix(".tmp")
    with open(tmp_path, "w") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)
    tmp_path.replace(_REGISTRY_PATH)


def init_registry() -> dict:
    """Initialize model registry by scanning version directories.

    Called at server startup. Discovers all vN/ directories under
    /app/models/ and populates registry.json if empty.
    """
    if not _MODEL_BASE.exists():
        return {"status": "no_models_dir", "path": str(_MODEL_BASE)}

    registry = _read_registry()

    # Scan for version directories
    discovered = {}
    for d in sorted(_MODEL_BASE.iterdir()):
        if not d.is_dir() or not d.name.startswith("v"):
            continue
        try:
            version_num = int(d.name[1:])
        except ValueError:
            continue
        onnx_files = sorted([p.name for p in d.glob("*.onnx")])
        json_files = sorted([p.name for p in d.glob("*.json")])
        discovered[d.name] = {
            "path": str(d),
            "onnx_models": onnx_files,
            "metadata_files": json_files,
            "model_count": len(onnx_files),
            "discovered_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    # Merge discovered into registry
    for vname, vinfo in discovered.items():
        if vname not in registry.get("versions", {}):
            registry.setdefault("versions", {})[vname] = vinfo
        else:
            # Update model list (new models may have been added)
            registry["versions"][vname].update(vinfo)

    # Determine current version
    current = None
    if _CURRENT_LINK.exists() and _CURRENT_LINK.is_symlink():
        try:
            resolved = _CURRENT_LINK.resolve()
            current = resolved.name
        except OSError:
            pass

    registry["current_version"] = current
    registry["last_scan_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if not registry.get("activation_history") and current:
        registry["activation_history"] = [current]

    _write_registry(registry)
    return registry


def list_versions() -> dict:
    """Get all model versions with metadata."""
    registry = _read_registry()
    return {
        "versions": registry.get("versions", {}),
        "current": registry.get("current_version"),
        "activation_history": registry.get("activation_history", []),
        "base_path": str(_MODEL_BASE),
        "version_count": len(registry.get("versions", {})),
        "_gw_source": "pipeline-live",
    }


def get_current_version() -> Optional[str]:
    """Get the currently active model version name (e.g. 'v1')."""
    registry = _read_registry()
    return registry.get("current_version")


def activate_version(version: str) -> dict:
    """Activate a model version by updating the /app/models/current symlink.

    Args:
        version: Version name, e.g. "v2"

    Returns:
        Status dict with activation result.

    Raises:
        FileNotFoundError: If version directory doesn't exist
        OSError: If symlink operation fails
    """
    target_dir = _MODEL_BASE / version
    if not target_dir.exists() or not target_dir.is_dir():
        available = [
            d.name for d in _MODEL_BASE.iterdir()
            if d.is_dir() and d.name.startswith("v")
        ]
        raise FileNotFoundError(
            f"Version '{version}' not found. Available: {', '.join(sorted(available))}"
        )

    # Atomic symlink update: create temp link, then rename
    tmp_link = _MODEL_BASE / ".current_tmp"
    try:
        if tmp_link.exists() or tmp_link.is_symlink():
            tmp_link.unlink()
        tmp_link.symlink_to(target_dir)
        tmp_link.replace(_CURRENT_LINK)
    except OSError as e:
        if tmp_link.exists():
            tmp_link.unlink()
        raise OSError(f"Failed to activate version '{version}': {e}")

    # Update registry
    registry = _read_registry()
    old_version = registry.get("current_version")
    registry["current_version"] = version
    history = registry.setdefault("activation_history", [])
    history.append(version)
    # Keep only last 20 entries
    if len(history) > 20:
        registry["activation_history"] = history[-20:]
    _write_registry(registry)

    return {
        "status": "activated",
        "version": version,
        "previous_version": old_version,
        "path": str(target_dir),
        "_gw_source": "pipeline-live",
    }


def rollback_version() -> dict:
    """Rollback to the previous version in activation history.

    Returns:
        Status dict. If no rollback target, returns status="no_rollback_available".
    """
    registry = _read_registry()
    history = registry.get("activation_history", [])

    if len(history) < 2:
        return {
            "status": "no_rollback_available",
            "current_version": history[-1] if history else None,
            "note": "Need 2+ activations in history for rollback",
            "_gw_source": "pipeline-live",
        }

    current = history[-1]
    target = history[-2]

    target_dir = _MODEL_BASE / target
    if not target_dir.exists():
        return {
            "status": "rollback_failed",
            "error": f"Rollback target '{target}' directory not found on disk",
            "current_version": current,
            "_gw_source": "pipeline-error",
        }

    # Atomic symlink update
    tmp_link = _MODEL_BASE / ".current_tmp"
    try:
        if tmp_link.exists() or tmp_link.is_symlink():
            tmp_link.unlink()
        tmp_link.symlink_to(target_dir)
        tmp_link.replace(_CURRENT_LINK)
    except OSError as e:
        if tmp_link.exists():
            tmp_link.unlink()
        return {
            "status": "rollback_failed",
            "error": str(e),
            "current_version": current,
            "_gw_source": "pipeline-error",
        }

    registry["current_version"] = target
    history.append(target)  # Record the rollback as a new activation
    registry["activation_history"] = history[-20:]
    _write_registry(registry)

    return {
        "status": "rolled_back",
        "from_version": current,
        "to_version": target,
        "_gw_source": "pipeline-live",
    }


def add_version_metadata(version: str, metadata: dict) -> dict:
    """Add or update metadata for a specific version.

    Args:
        version: Version name, e.g. "v2"
        metadata: Dict with training_date, accuracy, notes, etc.
    """
    registry = _read_registry()
    if version not in registry.get("versions", {}):
        raise FileNotFoundError(f"Version '{version}' not registered. Run init_registry() first.")

    registry["versions"][version]["metadata"] = metadata
    registry["versions"][version]["metadata_updated_utc"] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
    )
    _write_registry(registry)
    return {"status": "metadata_updated", "version": version, "_gw_source": "pipeline-live"}
