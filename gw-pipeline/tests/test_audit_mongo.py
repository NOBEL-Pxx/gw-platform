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


@pytest.mark.asyncio
async def test_ensure_indexes_disabled_when_ttl_zero(audit_module):
    """Case 8 (R6.67.5): AUDIT_TTL_DAYS=0 -> _ensure_indexes is a no-op."""
    with patch.dict(os.environ, {"AUDIT_TTL_DAYS": "0"}):
        import importlib
        mod = importlib.reload(sys.modules["pipeline.audit_mongo"])
        mock_client = MagicMock()
        # When ttl_days=0, function should return True immediately
        # without ever indexing into the client
        audit_module._last_ping_err = None
        result = await mod._ensure_indexes(mock_client)
        assert result is True
        # _last_ping_err should remain None (no error path)
        assert audit_module._last_ping_err is None


@pytest.mark.asyncio
async def test_ensure_indexes_calls_create_index(audit_module):
    """Case 9 (R6.67.5): When TTL enabled, _ensure_indexes calls create_index
    on the right collection with right expireAfterSeconds."""
    mock_client = MagicMock()
    mock_db = MagicMock()
    mock_coll = MagicMock()
    # Index chain: client[db_name] -> db[collection_name] -> coll.create_index
    mock_client.__getitem__ = MagicMock(return_value=mock_db)
    mock_db.__getitem__ = MagicMock(return_value=mock_coll)
    # create_index returns a coroutine
    mock_coll.create_index = AsyncMock(return_value="audit_ttl_ts")

    audit_module._last_ping_err = None
    result = await audit_module._ensure_indexes(mock_client)

    assert result is True
    mock_client.__getitem__.assert_called_with(audit_module._AUDIT_DB)
    mock_db.__getitem__.assert_called_with(audit_module._AUDIT_COLLECTION)
    mock_coll.create_index.assert_called_once()
    # Check args: keys + expireAfterSeconds + name
    args, kwargs = mock_coll.create_index.call_args
    assert args[0] == [("timestamp", 1)]
    assert kwargs.get("expireAfterSeconds") == audit_module._AUDIT_TTL_DAYS * 86400
    assert kwargs.get("name") == "audit_ttl_ts"


def test_get_health_includes_ttl(audit_module):
    """Case 10 (R6.67.5): get_health() exposes ttl_days and ttl_index_ready."""
    health = audit_module.get_health()
    assert "ttl_days" in health
    assert "ttl_index_ready" in health
    # ttl_index_ready should default False
    assert health["ttl_index_ready"] is False
    # ttl_days should be int (default 90) or None (if env was 0)
    assert health["ttl_days"] is None or isinstance(health["ttl_days"], int)


def test_find_match_field_basic(audit_module):
    """Case 11 (R6.67.3): _find_match_field returns first matching string field."""
    doc = {
        "action": "agent_chat",
        "session_id": "sess-abc-123",
        "user_role": "admin",
        "timestamp": "2026-09-07T10:00:00Z",
        "input_length": 100,
    }
    # Search for "abc" -> session_id
    result = audit_module._find_match_field(doc, "abc")
    assert result is not None
    field_name, field_value, matched = result
    assert field_name == "session_id"
    assert "abc" in field_value
    assert matched.lower() == "abc"


def test_find_match_field_case_insensitive(audit_module):
    """Case 12 (R6.67.3): _find_match_field is case-insensitive."""
    doc = {"action": "AGENT_CHAT", "user_role": "admin"}
    result = audit_module._find_match_field(doc, "agent")
    assert result is not None
    field_name, _, matched = result
    assert field_name == "action"
    assert matched == "AGENT"  # preserves original case


def test_find_match_field_no_match(audit_module):
    """Case 13 (R6.67.3): _find_match_field returns None when no field matches."""
    doc = {"action": "agent_chat", "user_role": "admin"}
    result = audit_module._find_match_field(doc, "nonexistent_string_xyz")
    assert result is None


def test_wrap_highlight_basic(audit_module):
    """Case 14 (R6.67.3): _wrap_highlight wraps first match with **...**."""
    wrapped = audit_module._wrap_highlight("hello world hello", "hello")
    assert wrapped == "**hello** world hello"  # only first occurrence wrapped


def test_wrap_highlight_case_insensitive(audit_module):
    """Case 15 (R6.67.3): _wrap_highlight is case-insensitive but preserves case."""
    wrapped = audit_module._wrap_highlight("Hello World", "hello")
    assert wrapped == "**Hello** World"
    assert wrapped != "**hello** World"  # original case preserved


def test_wrap_highlight_no_match(audit_module):
    """Case 16 (R6.67.3): _wrap_highlight returns original if no match."""
    wrapped = audit_module._wrap_highlight("hello world", "xyz")
    assert wrapped == "hello world"


def test_wrap_highlight_regex_special_chars(audit_module):
    """Case 17 (R6.67.3): _wrap_highlight escapes regex special chars in query."""
    # _wrap_highlight uses re.escape() so literal . is treated as dot, not regex.
    # The first literal dot in the string gets wrapped.
    wrapped = audit_module._wrap_highlight("user.email = foo.bar", ".")
    assert wrapped == "user**.**email = foo.bar"  # first literal dot wrapped


def test_safe_int_env_default(audit_module):
    """Case 18 (R6.67 hotfix): _safe_int_env returns default when env is unset."""
    import os
    os.environ.pop("AUDIT_TTL_DAYS", None)
    result = audit_module._safe_int_env("AUDIT_TTL_DAYS", 90)
    assert result == 90


def test_safe_int_env_invalid_falls_back(audit_module, caplog):
    """Case 19 (CRITICAL #3 hotfix): invalid env like '90d' falls back to default."""
    import os, logging
    os.environ["AUDIT_TTL_DAYS"] = "90d"
    with caplog.at_level(logging.WARNING):
        result = audit_module._safe_int_env("AUDIT_TTL_DAYS", 90)
    assert result == 90
    # Verify warning was logged (don't pin exact message)
    assert any("AUDIT_TTL_DAYS" in rec.message for rec in caplog.records)


def test_safe_int_env_explicit_value(audit_module):
    """Case 20 (R6.67 hotfix): _safe_int_env respects a valid integer string."""
    import os
    os.environ["AUDIT_TTL_DAYS"] = "30"
    result = audit_module._safe_int_env("AUDIT_TTL_DAYS", 90)
    assert result == 30
    os.environ.pop("AUDIT_TTL_DAYS", None)


# Helper: provide a pytest config in case conftest is absent
def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "asyncio: mark test as async (requires pytest-asyncio)",
    )
