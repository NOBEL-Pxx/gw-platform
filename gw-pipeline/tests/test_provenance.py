"""v4.38: Tests for provenance.py (Fix #4)."""
import pytest
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unittest.mock import patch, MagicMock, AsyncMock
from pipeline.provenance import (
    ProvenanceManager, get_provenance_manager, extract_fits_provenance,
)


class TestFitsProvenanceExtraction:
    """Tests for extract_fits_provenance — no MongoDB needed."""

    def test_extract_standard_keywords(self):
        """Standard FITS header keywords map to provenance fields."""
        header = {
            "ORIGIN": "Lanzhou University",
            "TELESCOP": "AliCPT-1",
            "INSTRUME": "CMB Receiver",
            "OBJECT": "CMB Field 1",
            "DATE-OBS": "2024-06-15",
        }
        prov = extract_fits_provenance(header)
        assert prov["origin"] == "Lanzhou University"
        assert prov["telescope"] == "AliCPT-1"
        assert prov["instrument"] == "CMB Receiver"
        assert prov["object"] == "CMB Field 1"
        assert prov["date_obs"] == "2024-06-15"

    def test_empty_header_returns_empty(self):
        """Empty header returns empty dict."""
        prov = extract_fits_provenance({})
        assert prov == {}

    def test_missing_keywords_ignored(self):
        """Missing keywords don't appear in output."""
        header = {"TELESCOP": "DSS2"}
        prov = extract_fits_provenance(header)
        assert "origin" not in prov
        assert prov["telescope"] == "DSS2"

    def test_whitespace_stripped(self):
        """String values have whitespace stripped."""
        header = {"TELESCOP": "  DSS2  ", "OBJECT": "  M31  "}
        prov = extract_fits_provenance(header)
        assert prov["telescope"] == "DSS2"
        assert prov["object"] == "M31"

    def test_reference_keyword(self):
        """REFERENC keyword is mapped."""
        header = {"REFERENC": "2025A&A...635A..12L"}
        prov = extract_fits_provenance(header)
        assert prov["reference"] == "2025A&A...635A..12L"


class TestProvenanceManager:
    """Unit tests for ProvenanceManager (no MongoDB)."""

    @pytest.mark.asyncio
    async def test_get_doi_without_mongo_returns_none(self):
        mgr = ProvenanceManager()
        mgr._mongo_available = False
        result = await mgr.get_doi("10.xxxx/test")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_dois_without_mongo(self):
        mgr = ProvenanceManager()
        mgr._mongo_available = False
        result = await mgr.list_dois()
        assert result["dois"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_link_observation_without_mongo(self):
        mgr = ProvenanceManager()
        mgr._mongo_available = False
        result = await mgr.link_observation("10.xxxx/test", "uuid-001")
        assert result is False

    @pytest.mark.asyncio
    async def test_provenance_chain_without_mongo(self):
        mgr = ProvenanceManager()
        mgr._mongo_available = False
        chain = await mgr.get_provenance_chain("uuid-001")
        assert chain == []

    @pytest.mark.asyncio
    async def test_record_provenance_without_mongo(self):
        mgr = ProvenanceManager()
        mgr._mongo_available = False
        result = await mgr.record_provenance("uuid-001", {
            "survey_name": "AliCPT",
            "processing_pipeline": "v4.38",
        })
        assert result is False

    @pytest.mark.asyncio
    async def test_register_doi_raises_without_mongo(self):
        mgr = ProvenanceManager()
        mgr._mongo_available = False
        with pytest.raises(RuntimeError, match="MongoDB not available"):
            await mgr.register_doi({"title": "Test Dataset"})

    def test_singleton(self):
        a = get_provenance_manager()
        b = get_provenance_manager()
        assert a is b
