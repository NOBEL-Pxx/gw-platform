#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R6.26 — Per-user daily LLM quota (Python / MongoDB side).

The Java backend (LlmController.java) has a GLOBAL AtomicInteger daily count
shared by ALL users. With multiple users this leads to:
  - One user hogging the quota for the day
  - Free riders on shared admin accounts
  - No way to grant extra quota to power users

This module provides the Python-side equivalent used by gw-pipeline when it
calls DeepSeek API directly (e.g. local_llm.py, llm_routes.py). The Java
backend should adopt the same schema (see LLM_PER_USER_QUOTA_R6.26.md).

Schema (MongoDB collection: llm_user_quotas):
    {
      "_id": "<username>",
      "daily_limit": 50,           # default, overridable per-user
      "is_admin": false,            # admins bypass quota
      "used_today": 3,
      "reset_date_utc": "2026-09-01",  # date the counter resets at midnight UTC
      "last_request_utc": "2026-09-01T14:23:11Z"
    }

API:
    quota = UserQuota(mongo_collection)
    ok, info = quota.check_and_increment(user_id, cost=1)
    if not ok: raise HTTPException(429, info["message"])

Configuration via env:
    GW_LLM_DEFAULT_DAILY_QUOTA = 50
    GW_LLM_ADMIN_BYPASS       = true

Thread/async safety: uses MongoDB atomic findOneAndUpdate ($inc + $set) so
concurrent requests from the same user do not double-count.
"""
from __future__ import annotations

import os
import datetime
import logging
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)


class UserQuota:
    """MongoDB-backed per-user daily LLM quota tracker."""

    DEFAULT_DAILY_QUOTA = 50
    ADMIN_BYPASS = True
    COLLECTION_NAME = "llm_user_quotas"

    def __init__(self, mongo_db, default_quota: Optional[int] = None, admin_bypass: Optional[bool] = None):
        """Args:
            mongo_db: a pymongo Database handle (collection is auto-created)
        """
        self._col = mongo_db[self.COLLECTION_NAME]
        self._default_quota = default_quota or int(os.environ.get("GW_LLM_DEFAULT_DAILY_QUOTA", self.DEFAULT_DAILY_QUOTA))
        self._admin_bypass = (
            admin_bypass
            if admin_bypass is not None
            else os.environ.get("GW_LLM_ADMIN_BYPASS", "true").lower() not in ("0", "false", "no")
        )
        # Create index for TTL + uniqueness (safe to call repeatedly)
        try:
            self._col.create_index("_id")
        except Exception as e:
            logger.warning("Could not create _id index on %s: %s", self.COLLECTION_NAME, e)
        logger.info(
            "R6.26 UserQuota initialized: default=%d/day admin_bypass=%s",
            self._default_quota, self._admin_bypass,
        )

    # ── Core API ────────────────────────────────────────────────────────
    def check_and_increment(self, user_id: str, cost: int = 1) -> Tuple[bool, dict]:
        """Check quota and atomically increment counter.

        Returns:
            (True, {"used": N, "limit": M, "remaining": M-N})  if allowed
            (False, {"used": N, "limit": M, "remaining": 0, "message": "..."})  if denied
        """
        today_utc = datetime.datetime.now(timezone := datetime.timezone.utc).date().isoformat()
        is_admin = self._is_admin(user_id)

        # Atomically: ensure doc exists, reset counter if date rolled over, increment
        from pymongo import ReturnDocument
        try:
            doc = self._col.find_one_and_update(
                {"_id": user_id},
                {
                    "$setOnInsert": {
                        "daily_limit": self._default_quota,
                        "is_admin": is_admin,
                        "reset_date_utc": today_utc,
                    },
                    "$set": {"last_request_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()},
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except Exception as e:
            # Fail open on Mongo errors -- don't block LLM access on quota system fault
            logger.error("UserQuota Mongo error for %s, failing open: %s", user_id, e)
            return True, {"used": 0, "limit": self._default_quota, "remaining": self._default_quota, "note": "quota system error"}

        # Admin bypass
        if self._admin_bypass and doc.get("is_admin"):
            return True, {
                "used": doc.get("used_today", 0),
                "limit": doc.get("daily_limit", self._default_quota),
                "remaining": -1,  # sentinel = unlimited
                "admin": True,
            }

        limit = doc.get("daily_limit", self._default_quota)
        stored_date = doc.get("reset_date_utc")

        # Date rolled over -- reset counter
        if stored_date != today_utc:
            self._col.update_one(
                {"_id": user_id},
                {"$set": {"used_today": 0, "reset_date_utc": today_utc}},
            )
            current_used = 0
        else:
            current_used = doc.get("used_today", 0)

        # Quota exceeded?
        if current_used + cost > limit:
            return False, {
                "used": current_used,
                "limit": limit,
                "remaining": 0,
                "message": f"Daily LLM quota exceeded ({current_used}/{limit}). Resets at midnight UTC.",
                "reset_date_utc": today_utc,
            }

        # Allowed -- atomic increment
        new_doc = self._col.find_one_and_update(
            {"_id": user_id, "reset_date_utc": today_utc},
            {"$inc": {"used_today": cost}},
            return_document=ReturnDocument.AFTER,
        )
        new_used = (new_doc or {}).get("used_today", current_used + cost)
        return True, {
            "used": new_used,
            "limit": limit,
            "remaining": max(0, limit - new_used),
        }

    # ── Admin helpers ────────────────────────────────────────────────────
    def set_user_limit(self, user_id: str, daily_limit: int, is_admin: Optional[bool] = None) -> None:
        """Admin: override a user's daily limit (or mark them as admin)."""
        update: dict[str, Any] = {"daily_limit": int(daily_limit)}
        if is_admin is not None:
            update["is_admin"] = bool(is_admin)
        self._col.update_one({"_id": user_id}, {"$set": update}, upsert=True)

    def get_usage(self, user_id: str) -> dict:
        """Return current usage for a user (or default empty dict)."""
        doc = self._col.find_one({"_id": user_id}) or {}
        return {
            "user_id": user_id,
            "daily_limit": doc.get("daily_limit", self._default_quota),
            "used_today": doc.get("used_today", 0),
            "is_admin": doc.get("is_admin", False),
            "reset_date_utc": doc.get("reset_date_utc", None),
            "last_request_utc": doc.get("last_request_utc", None),
        }

    def list_users(self, skip: int = 0, limit: int = 100) -> list[dict]:
        """Admin: list all users with their quotas."""
        cursor = self._col.find().skip(skip).limit(limit)
        out = []
        for doc in cursor:
            out.append({
                "user_id": doc["_id"],
                "daily_limit": doc.get("daily_limit", self._default_quota),
                "used_today": doc.get("used_today", 0),
                "is_admin": doc.get("is_admin", False),
            })
        return out

    # ── Internal ─────────────────────────────────────────────────────────
    def _is_admin(self, user_id: str) -> bool:
        # Convention: users in GW_ADMIN_USERS env (comma-separated) are admins
        admins_env = os.environ.get("GW_ADMIN_USERS", "")
        admins = {u.strip() for u in admins_env.split(",") if u.strip()}
        return user_id in admins


# ── Module-level singleton (initialized on first use) ──────────────────
_INSTANCE: UserQuota | None = None


def get_user_quota(mongo_db=None) -> UserQuota:
    """Lazy-init the singleton. Requires mongo_db (Database) on first call."""
    global _INSTANCE
    if _INSTANCE is None:
        if mongo_db is None:
            raise RuntimeError("UserQuota not initialized -- call get_user_quota(mongo_db) first")
        _INSTANCE = UserQuota(mongo_db)
    return _INSTANCE
