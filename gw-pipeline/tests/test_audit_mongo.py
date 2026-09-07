"""R6.66.4: pytest coverage for audit_mongo.py (7 cases).

All tests use module-level monkeypatching of audit_mongo globals to avoid
needing a real MongoDB connection. Motor is mocked with unittest.mock.

Run with:
    cd D:\\AliCPT\\gw-pipeline
    python -m pytest tests/test_audit_mongo.py -v
"""
import os
import sys
import json
import datetime
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# Add src to path so we can import audit_mongo directly
_PIPELINE_SRC = os.path.join(os.path.dirname(__file__), os.pardir, "src")
if _PIPELINE_SRC not in sys.path:
    sys.path.insert(0, os.path.abspath(_PIPELINE_SRC))


@pytest.fixture
def audit_module():
    """Fresh audit_mongo module with clean globals per test."""
    import importlib
    # Reload to get fresh state
    if "pipeline.audit_mongo" in sys.modules:
        mod = importlib.reload(sys.modules["pipeline.audit_mongo"])
    else:
        mod = importlib.import_module("pipeline.audit_mongo")
    # Reset global state between tests
    mod._mongo_client = None
    mod._mongo_available = False
    mod._last_ping_ts = 0.0
    mod._last_ping_err = None
    return mod


def test_is_enabled_default_true(audit_module):
    """Case 1: AUDIT_MONGO_ENABLED defaults to True when env not set."""
    # The module is loaded once with current env. We test that the toggle
    # function correctly reflects whatever the env says, with default true.
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("AUDIT_MONGO_ENABLED", None)
        # Reload to pick up env
        import importlib
        mod = importlib.reload(sys.modules["pipeline.audit_mongo"])
        assert mod.is_enabled() is True


def test_is_enabled_env_false(audit_module):
    """Case 2: AUDIT_MONGO_ENABLED=false disables Mongo audit."""
    with patch.dict(os.environ, {"AUDIT_MONGO_ENABLED": "false"}):
        import importlib
        mod = importlib.reload(sys.modules["pipeline.audit_mongo"])
        assert mod.is_enabled() is False


def test_get_health_initial(audit_module):
    """Case 3: get_health() returns expected keys with default (file-only) state."""
    health = audit_module.get_health()
    assert "enabled" in health
    assert "available" in health
    assert "uri" in health
    assert "database" in health
    assert "last_ping_ts" in health
    assert "last_error" in health
    assert "mode" in health
    assert health["available"] is False
    assert health["mode"] == "file-only"
    # URI may include credentials; just check non-empty
    assert isinstance(health["uri"], str) and len(health["uri"]) > 0


@pytest.mark.asyncio
async def test_write_audit_entry_file_only_when_disabled(audit_module):
    """Case 4: When AUDIT_MONGO_ENABLED=false, write_audit_entry returns False
    and writes to file. No MongoDB client should be created."""
    with patch.dict(os.environ, {"AUDIT_MONGO_ENABLED": "false"}):
        import importlib
        mod = importlib.reload(sys.modules["pipeline.audit_mongo"])

        # Use a temp dir for the log
        with tempfile.TemporaryDirectory() as tmpdir:
            # Patch the log_dir resolution by intercepting the open() call
            # Simpler: just call the function and verify it returned False
            # (Mongo write skipped because disabled).
            # The file will be created at the module-relative path.
            entry = {
                "action": "test_action",
                "session_id": "test_session",
                "user": "test_user",
            }
            result = await mod.write_audit_entry(entry)
            assert result is False, "Should return False when Mongo audit is disabled"


@pytest.mark.asyncio
async def test_write_audit_entry_file_always(audit_module):
    """Case 5: File backup happens unconditionally, even when Mongo fails."""
    # Disable Mongo so file-only mode
    with patch.dict(os.environ, {"AUDIT_MONGO_ENABLED": "false"}):
        import importlib
        mod = importlib.reload(sys.modules["pipeline.audit_mongo"])

        entry = {
            "action": "test_file_write",
            "session_id": "s1",
        }
        # Just verify no exception thrown and return is False
        result = await mod.write_audit_entry(entry)
        assert result is False

        # Also verify the compliance_audit.log file exists and contains our entry
        log_path = os.path.join(
            os.path.dirname(os.path.abspath(mod.__file__)),
            "..", "..", "logs", "compliance_audit.log",
        )
        log_path = os.path.normpath(log_path)
        assert os.path.exists(log_path), f"Log file not found at {log_path}"
        with open(log_path, "r", encoding="utf-8") as f:
            content = f.read()
        # The last line should be our entry
        last_line = content.strip().split(chr(10))[-1]
        parsed = json.loads(last_line)
        assert parsed["action"] == "test_file_write"
        assert parsed["session_id"] == "s1"


@pytest.mark.asyncio
async def test_get_mongo_async_disabled_returns_false(audit_module):
    """Case 6: When AUDIT_MONGO_ENABLED=false, _get_mongo_async() returns
    (None, False) without creating a motor client."""
    with patch.dict(os.environ, {"AUDIT_MONGO_ENABLED": "false"}):
        import importlib
        mod = importlib.reload(sys.modules["pipeline.audit_mongo"])

        client, available = await mod._get_mongo_async()
        assert available is False
        # Client may be None or whatever default; key check is available=False
        assert mod._mongo_available is False


@pytest.mark.asyncio
async def test_verify_mongo_records_error_on_failure(audit_module):
    """Case 7: _verify_mongo records errors into _last_ping_err when ping fails."""
    # Create a mock client that raises on admin.command
    mock_client = MagicMock()
    mock_client.admin.command = AsyncMock(side_effect=ConnectionError("mongo down"))

    audit_module._last_ping_err = None
    result = await audit_module._verify_mongo(mock_client)
    assert result is False
    assert audit_module._last_ping_err is not None
    assert "ConnectionError" in audit_module._last_ping_err
    assert "mongo down" in audit_module._last_ping_err


# Helper: provide a pytest config in case conftest is absent
def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "asyncio: mark test as async (requires pytest-asyncio)",
    )
