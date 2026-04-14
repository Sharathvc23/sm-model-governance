"""Tests for PostgresApprovalStore with mocked psycopg2.

# Step 1 — Assumption Audit
# - PostgresApprovalStore uses psycopg2 ThreadedConnectionPool
# - store() executes INSERT ... ON CONFLICT DO UPDATE
# - get() returns ModelApproval from row or None
# - revoke() executes UPDATE ... SET status='revoked'
# - _row_to_approval handles both datetime objects and ISO strings

# Step 2 — Gap Analysis
# - All CRUD paths tested with mocked cursor
# - _row_to_approval string date parsing tested

# Step 3 — Break It List
# - Non-existent get returns None (covered)
# - Revoke non-existent returns False (covered)
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from sm_governance.approval import ModelApproval

# ---------------------------------------------------------------------------
# Build a fake psycopg2 module tree so we can import postgres.py
# ---------------------------------------------------------------------------


def _make_fake_psycopg2() -> ModuleType:
    """Create a minimal fake psycopg2 package with pool and extras."""
    psycopg2 = ModuleType("psycopg2")
    psycopg2_pool = ModuleType("psycopg2.pool")
    psycopg2_extras = ModuleType("psycopg2.extras")

    psycopg2_pool.ThreadedConnectionPool = MagicMock()
    psycopg2_extras.Json = MagicMock(side_effect=lambda x: x)

    psycopg2.pool = psycopg2_pool
    psycopg2.extras = psycopg2_extras

    return psycopg2, psycopg2_pool, psycopg2_extras


@pytest.fixture(autouse=True)
def _fake_psycopg2(monkeypatch: pytest.MonkeyPatch):
    """Inject fake psycopg2 into sys.modules for every test."""
    fake, fake_pool, fake_extras = _make_fake_psycopg2()

    monkeypatch.setitem(sys.modules, "psycopg2", fake)
    monkeypatch.setitem(sys.modules, "psycopg2.pool", fake_pool)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", fake_extras)

    yield fake, fake_pool, fake_extras


@pytest.fixture
def mock_pool():
    """A fresh MagicMock standing in for ThreadedConnectionPool."""
    pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()

    pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)

    return pool, mock_conn, mock_cursor


@pytest.fixture
def store(mock_pool):
    """Create a PostgresApprovalStore with mocked pool, bypassing __init__."""
    pool, _, _ = mock_pool

    with patch("sm_governance._compat.has_psycopg2", return_value=True):
        from sm_governance.stores.postgres import PostgresApprovalStore

        obj = PostgresApprovalStore.__new__(PostgresApprovalStore)
        obj._pool = pool

    return obj


@pytest.fixture
def sample_approval() -> ModelApproval:
    """A complete approval for testing."""
    approval = ModelApproval(
        approval_id="approval:pg-test-001",
        model_id="model-pg-test",
        weights_hash="sha256:aabbccdd" * 4,
        approved_by="governance-admin",
        approved_at=datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
        expires_at=datetime(2025, 12, 1, 10, 0, 0, tzinfo=timezone.utc),
        profile="production",
        correlation_id="corr-pg-001",
        signature="sig-hex-placeholder",
        status="active",
        approved_environments=["staging", "production"],
        approved_scopes=["inference"],
        required_approvers=1,
        approver_signatures={"governance-admin": "sig-admin"},
    )
    return approval


class TestStoreMethod:
    """Tests for PostgresApprovalStore.store()."""

    def test_store_executes_insert_with_correct_params(
        self, store, mock_pool, sample_approval
    ):
        _, _, mock_cursor = mock_pool

        store.store(sample_approval)

        mock_cursor.execute.assert_called_once()
        sql, params = mock_cursor.execute.call_args[0]
        assert "INSERT INTO model_approvals" in sql
        assert "ON CONFLICT (approval_id) DO UPDATE" in sql
        assert params[0] == "approval:pg-test-001"
        assert params[1] == "model-pg-test"
        assert params[2] == "sha256:aabbccdd" * 4
        assert params[3] == "governance-admin"
        assert params[9] == "active"
        assert params[10] == ["staging", "production"]
        assert params[11] == ["inference"]


class TestGetMethod:
    """Tests for PostgresApprovalStore.get()."""

    def test_get_returns_model_approval_when_row_found(self, store, mock_pool):
        _, _, mock_cursor = mock_pool

        mock_cursor.fetchone.return_value = (
            "approval:found",
            "model-found",
            "weighthash",
            "admin",
            datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
            datetime(2025, 12, 1, 10, 0, 0, tzinfo=timezone.utc),
            "default",
            "corr-1",
            "sig-1",
            "active",
            ["prod"],
            ["inference"],
            1,
            {"admin": "sig-admin"},
            datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
            datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
        )
        mock_cursor.description = [
            ("approval_id",),
            ("model_id",),
            ("weights_hash",),
            ("approved_by",),
            ("approved_at",),
            ("expires_at",),
            ("profile",),
            ("correlation_id",),
            ("signature",),
            ("status",),
            ("approved_environments",),
            ("approved_scopes",),
            ("required_approvers",),
            ("approver_signatures",),
            ("created_at",),
            ("updated_at",),
        ]

        result = store.get("model-found")

        assert result is not None
        assert isinstance(result, ModelApproval)
        assert result.approval_id == "approval:found"
        assert result.model_id == "model-found"
        assert result.status == "active"
        assert result.approved_environments == ["prod"]

    def test_get_returns_none_when_no_row(self, store, mock_pool):
        _, _, mock_cursor = mock_pool
        mock_cursor.fetchone.return_value = None

        result = store.get("nonexistent-model")

        assert result is None


class TestIsApprovedMethod:
    """Tests for PostgresApprovalStore.is_approved()."""

    def test_returns_true_for_active_non_expired_approval(self, store, mock_pool):
        _, _, mock_cursor = mock_pool

        future = datetime.now(timezone.utc) + timedelta(days=30)
        mock_cursor.fetchone.return_value = (
            "approval:active",
            "model-active",
            "hash",
            "admin",
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            future,
            "default",
            None,
            "sig",
            "active",
            None,
            None,
            1,
            {"admin": "sig"},
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        mock_cursor.description = [
            ("approval_id",),
            ("model_id",),
            ("weights_hash",),
            ("approved_by",),
            ("approved_at",),
            ("expires_at",),
            ("profile",),
            ("correlation_id",),
            ("signature",),
            ("status",),
            ("approved_environments",),
            ("approved_scopes",),
            ("required_approvers",),
            ("approver_signatures",),
            ("created_at",),
            ("updated_at",),
        ]

        assert store.is_approved("model-active") is True

    def test_returns_false_for_revoked_approval(self, store, mock_pool):
        _, _, mock_cursor = mock_pool

        future = datetime.now(timezone.utc) + timedelta(days=30)
        mock_cursor.fetchone.return_value = (
            "approval:revoked",
            "model-revoked",
            "hash",
            "admin",
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            future,
            "default",
            None,
            "sig",
            "revoked",
            None,
            None,
            1,
            {"admin": "sig"},
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        mock_cursor.description = [
            ("approval_id",),
            ("model_id",),
            ("weights_hash",),
            ("approved_by",),
            ("approved_at",),
            ("expires_at",),
            ("profile",),
            ("correlation_id",),
            ("signature",),
            ("status",),
            ("approved_environments",),
            ("approved_scopes",),
            ("required_approvers",),
            ("approver_signatures",),
            ("created_at",),
            ("updated_at",),
        ]

        assert store.is_approved("model-revoked") is False


class TestRevokeMethod:
    """Tests for PostgresApprovalStore.revoke()."""

    def test_revoke_executes_update_sql(self, store, mock_pool):
        _, _, mock_cursor = mock_pool
        mock_cursor.rowcount = 1

        result = store.revoke("model-to-revoke", "admin", "policy violation")

        assert result is True
        mock_cursor.execute.assert_called_once()
        sql, params = mock_cursor.execute.call_args[0]
        assert "UPDATE model_approvals" in sql
        assert "status = 'revoked'" in sql
        assert params == ("model-to-revoke",)

    def test_revoke_returns_false_when_nothing_updated(self, store, mock_pool):
        _, _, mock_cursor = mock_pool
        mock_cursor.rowcount = 0

        result = store.revoke("nonexistent", "admin", "reason")

        assert result is False


class TestRowToApproval:
    """Tests for PostgresApprovalStore._row_to_approval()."""

    def test_deserializes_complete_row(self, store):
        row = {
            "approval_id": "approval:row-test",
            "model_id": "model-row",
            "weights_hash": "rowweighthash",
            "approved_by": "row-admin",
            "approved_at": datetime(2025, 5, 1, 8, 30, 0, tzinfo=timezone.utc),
            "expires_at": datetime(2025, 11, 1, 8, 30, 0, tzinfo=timezone.utc),
            "profile": "staging",
            "correlation_id": "corr-row",
            "signature": "sig-row",
            "status": "active",
            "approved_environments": ["staging"],
            "approved_scopes": ["inference", "eval"],
            "required_approvers": 2,
            "approver_signatures": {
                "admin-a": "sig-a",
                "admin-b": "sig-b",
            },
        }

        result = store._row_to_approval(row)

        assert isinstance(result, ModelApproval)
        assert result.approval_id == "approval:row-test"
        assert result.model_id == "model-row"
        assert result.weights_hash == "rowweighthash"
        assert result.approved_by == "row-admin"
        assert result.approved_at == datetime(2025, 5, 1, 8, 30, 0, tzinfo=timezone.utc)
        assert result.expires_at == datetime(2025, 11, 1, 8, 30, 0, tzinfo=timezone.utc)
        assert result.profile == "staging"
        assert result.correlation_id == "corr-row"
        assert result.signature == "sig-row"
        assert result.status == "active"
        assert result.approved_environments == ["staging"]
        assert result.approved_scopes == ["inference", "eval"]
        assert result.required_approvers == 2
        assert result.approver_signatures == {"admin-a": "sig-a", "admin-b": "sig-b"}

    def test_deserializes_string_dates(self, store):
        """Verify ISO string dates get parsed to datetime objects."""
        row = {
            "approval_id": "approval:strdate",
            "model_id": "model-strdate",
            "approved_by": "admin",
            "approved_at": "2025-03-15T10:00:00+00:00",
            "expires_at": "2025-06-15T10:00:00+00:00",
            "approver_signatures": '{"admin": "sig"}',
        }

        result = store._row_to_approval(row)

        assert isinstance(result.approved_at, datetime)
        assert isinstance(result.expires_at, datetime)
        assert result.approver_signatures == {"admin": "sig"}
