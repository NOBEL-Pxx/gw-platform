"""
v4.38: Data Provenance & DOI Reference Manager (Fix #4)

Provides:
  - DOI registration and lookup (MongoDB-backed)
  - Observation-to-DOI linking
  - Provenance chain tracking (data lineage)
  - FITS header provenance extraction

Data Model (MongoDB: gw_provenance database):
  doi_registry    — DOI metadata records
  provenance      — Observation-level provenance records
  doi_links       — Many-to-many DOI ↔ observation links

Usage:
    from .provenance import get_provenance_manager
    mgr = get_provenance_manager()
    doi = await mgr.register_doi(title="AliCPT-1 Season 1", ...)
"""

from __future__ import annotations
import os, logging, datetime, uuid as _uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("gw.provenance")

_PROVENANCE_DB = os.getenv("GW_PROVENANCE_DB", "gw_provenance")


class ProvenanceManager:
    """Manage data provenance records and DOI references."""

    def __init__(self):
        self._client = None
        self._mongo_available = False

    async def _ensure_mongo(self):
        if self._client is not None:
            return
        try:
            import motor.motor_asyncio
            mongo_url = os.getenv("GW_MONGO_URL", "mongodb://mongodb:27017")
            self._client = motor.motor_asyncio.AsyncIOMotorClient(
                mongo_url, serverSelectionTimeoutMS=3000
            )
            await self._client.admin.command("ping")
            self._mongo_available = True
            logger.info("ProvenanceManager: MongoDB connected")
        except Exception as e:
            logger.warning("ProvenanceManager: MongoDB unavailable (%s)", e)
            self._mongo_available = False

    # ── DOI Registry ───────────────────────────────────────────────────

    async def register_doi(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Register a new DOI reference record.

        Required fields: title, creators (list), publisher, resource_type
        Optional: doi (auto-generated if missing), description, related_identifiers,
                  observation_ids, survey, bands, publication_year
        """
        await self._ensure_mongo()
        if not self._mongo_available:
            raise RuntimeError("MongoDB not available — cannot register DOI")

        doi = data.get("doi", f"10.5072/gw.{_uuid.uuid4().hex[:8]}")
        now = datetime.datetime.utcnow()

        record = {
            "doi": doi,
            "title": data["title"],
            "creators": data.get("creators", []),
            "publisher": data.get("publisher", "GravitationalWave Platform"),
            "publication_year": data.get("publication_year", now.year),
            "resource_type": data.get("resource_type", "Dataset"),
            "description": data.get("description", ""),
            "related_identifiers": data.get("related_identifiers", []),
            "observation_ids": data.get("observation_ids", []),
            "survey": data.get("survey", ""),
            "bands": data.get("bands", []),
            "created_at": now,
            "updated_at": now,
            "file_count": data.get("file_count", 0),
            "total_size_mb": data.get("total_size_mb", 0.0),
        }

        try:
            db = self._client[_PROVENANCE_DB]
            await db["doi_registry"].replace_one(
                {"doi": doi}, record, upsert=True
            )
            logger.info("DOI registered: %s", doi)
            return record
        except Exception as e:
            logger.error("DOI registration failed: %s", e)
            raise

    async def get_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        """Retrieve a DOI record by identifier."""
        await self._ensure_mongo()
        if not self._mongo_available:
            return None
        try:
            db = self._client[_PROVENANCE_DB]
            doc = await db["doi_registry"].find_one({"doi": doi})
            if doc:
                doc["_id"] = str(doc["_id"])
                if isinstance(doc.get("created_at"), datetime.datetime):
                    doc["created_at"] = doc["created_at"].isoformat() + "Z"
                if isinstance(doc.get("updated_at"), datetime.datetime):
                    doc["updated_at"] = doc["updated_at"].isoformat() + "Z"
            return doc
        except Exception as e:
            logger.error("get_doi failed: %s", e)
            return None

    async def list_dois(
        self, survey: str = None, page: int = 1, page_size: int = 20
    ) -> Dict[str, Any]:
        """List DOI records with optional survey filter."""
        await self._ensure_mongo()
        if not self._mongo_available:
            return {"dois": [], "total": 0, "page": page}

        try:
            db = self._client[_PROVENANCE_DB]
            filt = {}
            if survey:
                filt["survey"] = survey
            total = await db["doi_registry"].count_documents(filt)
            cursor = db["doi_registry"].find(filt).sort(
                "created_at", -1
            ).skip((page - 1) * page_size).limit(page_size)
            dois = []
            async for doc in cursor:
                doc["_id"] = str(doc["_id"])
                if isinstance(doc.get("created_at"), datetime.datetime):
                    doc["created_at"] = doc["created_at"].isoformat() + "Z"
                dois.append(doc)
            return {"dois": dois, "total": total, "page": page, "page_size": page_size}
        except Exception as e:
            logger.error("list_dois failed: %s", e)
            return {"dois": [], "total": 0, "page": page, "error": str(e)[:200]}

    # ── Observation Linking ─────────────────────────────────────────────

    async def link_observation(self, doi: str, observation_id: str) -> bool:
        """Link an observation UUID to a DOI record."""
        await self._ensure_mongo()
        if not self._mongo_available:
            return False
        try:
            db = self._client[_PROVENANCE_DB]
            await db["doi_links"].update_one(
                {"doi": doi, "observation_id": observation_id},
                {"$set": {
                    "doi": doi,
                    "observation_id": observation_id,
                    "linked_at": datetime.datetime.utcnow(),
                }},
                upsert=True,
            )
            # Also update the DOI record
            await db["doi_registry"].update_one(
                {"doi": doi},
                {"$addToSet": {"observation_ids": observation_id},
                 "$set": {"updated_at": datetime.datetime.utcnow()}},
            )
            return True
        except Exception as e:
            logger.error("link_observation failed: %s", e)
            return False

    async def get_provenance_chain(self, observation_id: str) -> List[Dict[str, Any]]:
        """Get the provenance chain for an observation.

        Returns chain of: DOIs it belongs to, processing history, linked datasets.
        """
        await self._ensure_mongo()
        chain = []

        if not self._mongo_available:
            return chain

        try:
            db = self._client[_PROVENANCE_DB]

            # Find linked DOIs
            doi_cursor = db["doi_links"].find({"observation_id": observation_id})
            async for link in doi_cursor:
                doi_doc = await db["doi_registry"].find_one({"doi": link["doi"]})
                if doi_doc:
                    doi_doc["_id"] = str(doi_doc["_id"])
                    chain.append({"type": "doi", "data": doi_doc})

            # Find provenance records
            prov_cursor = db["provenance"].find({"observation_id": observation_id})
            async for prov in prov_cursor:
                prov["_id"] = str(prov["_id"])
                chain.append({"type": "provenance", "data": prov})

        except Exception as e:
            logger.error("get_provenance_chain failed: %s", e)

        return chain

    async def record_provenance(
        self, observation_id: str, data: Dict[str, Any]
    ) -> bool:
        """Record a provenance event for an observation."""
        await self._ensure_mongo()
        if not self._mongo_available:
            return False
        try:
            record = {
                "observation_id": observation_id,
                "timestamp": datetime.datetime.utcnow(),
                "survey_name": data.get("survey_name", ""),
                "processing_pipeline": data.get("processing_pipeline", ""),
                "processing_version": data.get("processing_version", ""),
                "original_filename": data.get("original_filename", ""),
                "checksum_sha256": data.get("checksum_sha256", ""),
                "extra": data.get("extra", {}),
            }
            db = self._client[_PROVENANCE_DB]
            await db["provenance"].insert_one(record)
            return True
        except Exception as e:
            logger.error("record_provenance failed: %s", e)
            return False


# ── FITS Header Provenance Extraction ──────────────────────────────────

def extract_fits_provenance(header: Dict[str, Any]) -> Dict[str, Any]:
    """Extract provenance metadata from FITS header keywords.

    Standard keywords: ORIGIN, DATE, DATE-OBS, TELESCOP, INSTRUME,
    OBJECT, AUTHOR, REFERENC, CREATOR, VERSION
    """
    prov: Dict[str, Any] = {}
    key_map = {
        "origin": "ORIGIN",
        "date": "DATE",
        "date_obs": "DATE-OBS",
        "telescope": "TELESCOP",
        "instrument": "INSTRUME",
        "object": "OBJECT",
        "author": "AUTHOR",
        "reference": "REFERENC",
        "creator": "CREATOR",
        "version": "VERSION",
    }
    for prov_key, fits_key in key_map.items():
        val = header.get(fits_key, "")
        if isinstance(val, str):
            val = val.strip()
        if val:
            prov[prov_key] = str(val)

    return prov


# ── Singleton ───────────────────────────────────────────────────────────

_provenance_manager: Optional[ProvenanceManager] = None


def get_provenance_manager() -> ProvenanceManager:
    global _provenance_manager
    if _provenance_manager is None:
        _provenance_manager = ProvenanceManager()
    return _provenance_manager
