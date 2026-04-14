"""Tests for sm_governance.protocol integration functions.

# Step 1 — Assumption Audit
# - approval_to_integrity_facts converts ModelApproval to dict with governance key
# - create_provenance_with_approval requires sm-model-integrity-layer installed
# - has_quorum reflects signature count vs required_approvers

# Step 2 — Gap Analysis
# - Good coverage of dict structure, expiry handling, quorum logic
# - ImportError path tested with mock

# Step 3 — Break It List
# - Dict keys validated; quorum edge case covered
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from sm_governance.approval import ModelApproval
from sm_governance.protocol import approval_to_integrity_facts


@pytest.fixture
def approval_with_expiry() -> ModelApproval:
    """An approval with expires_at set."""
    approval = ModelApproval(
        approval_id="approval:test123",
        model_id="model-xyz",
        weights_hash="abc123def456",
        approved_by="governance-bob",
        approved_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        expires_at=datetime(2025, 9, 15, 12, 0, 0, tzinfo=timezone.utc),
        profile="production",
        status="active",
        approved_environments=["staging", "production"],
        approved_scopes=["inference", "fine-tune"],
        required_approvers=2,
    )
    approval.add_signature("governance-bob", "sig-bob")
    approval.add_signature("governance-carol", "sig-carol")
    return approval


@pytest.fixture
def approval_no_expiry() -> ModelApproval:
    """An approval with expires_at=None."""
    approval = ModelApproval(
        approval_id="approval:noexpiry",
        model_id="model-eternal",
        weights_hash="hash999",
        approved_by="governance-alice",
        approved_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        expires_at=None,
        profile="default",
        status="active",
        approved_environments=None,
        approved_scopes=None,
        required_approvers=1,
    )
    approval.add_signature("governance-alice", "sig-alice")
    return approval


class TestApprovalToIntegrityFacts:
    """Tests for approval_to_integrity_facts()."""

    def test_converts_approval_to_expected_dict_structure(
        self, approval_with_expiry: ModelApproval
    ) -> None:
        result = approval_to_integrity_facts(approval_with_expiry)

        assert "governance" in result
        gov = result["governance"]

        assert gov["approval_id"] == "approval:test123"
        assert gov["model_id"] == "model-xyz"
        assert gov["weights_hash"] == "abc123def456"
        assert gov["approved_by"] == "governance-bob"
        assert gov["approved_at"] == "2025-06-15T12:00:00+00:00"
        assert gov["expires_at"] == "2025-09-15T12:00:00+00:00"
        assert gov["status"] == "active"
        assert gov["profile"] == "production"
        assert gov["has_quorum"] is True
        assert gov["approved_environments"] == ["staging", "production"]
        assert gov["approved_scopes"] == ["inference", "fine-tune"]

    def test_all_expected_keys_present(
        self, approval_with_expiry: ModelApproval
    ) -> None:
        result = approval_to_integrity_facts(approval_with_expiry)
        gov = result["governance"]

        expected_keys = {
            "approval_id",
            "model_id",
            "weights_hash",
            "approved_by",
            "approved_at",
            "expires_at",
            "status",
            "profile",
            "has_quorum",
            "approved_environments",
            "approved_scopes",
        }
        assert set(gov.keys()) == expected_keys

    def test_expires_at_none_handled_correctly(
        self, approval_no_expiry: ModelApproval
    ) -> None:
        result = approval_to_integrity_facts(approval_no_expiry)
        gov = result["governance"]

        assert gov["expires_at"] is None
        # Other fields should still be populated
        assert gov["approval_id"] == "approval:noexpiry"
        assert gov["model_id"] == "model-eternal"
        assert gov["approved_at"] == "2025-01-01T00:00:00+00:00"
        assert gov["has_quorum"] is True

    def test_has_quorum_false_when_insufficient_signatures(self) -> None:
        approval = ModelApproval(
            approval_id="approval:noquorum",
            model_id="model-pending",
            weights_hash="hash000",
            approved_by="governance-alice",
            approved_at=datetime(2025, 3, 1, 0, 0, 0, tzinfo=timezone.utc),
            required_approvers=3,
        )
        # Only add 1 signature, but 3 required
        approval.add_signature("governance-alice", "sig-alice")

        result = approval_to_integrity_facts(approval)
        assert result["governance"]["has_quorum"] is False


class TestCreateProvenanceWithApprovalImportError:
    """Test that create_provenance_with_approval raises ImportError
    when sm-model-integrity-layer is not installed."""

    def test_raises_import_error_when_integrity_not_available(self) -> None:
        from sm_governance.protocol import create_provenance_with_approval

        approval = ModelApproval(
            model_id="model-test",
            weights_hash="testhash",
            approved_by="alice",
        )

        with (
            patch("sm_governance.protocol.has_sm_integrity", return_value=False),
            pytest.raises(ImportError, match="sm-model-integrity-layer"),
        ):
            create_provenance_with_approval(approval)
