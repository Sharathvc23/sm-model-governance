"""Tests for Ed25519 signing and verification.

# Step 1 — Assumption Audit
# - sign_approval uses Ed25519 private key over compute_hash() of approval
# - verify_approval re-computes hash and verifies Ed25519 signature
# - Wrong key -> verification fails; tampered fields -> verification fails
# - Empty signature returns False
# - Missing cryptography package raises ImportError

# Step 2 — Gap Analysis
# - R7 crypto forgery tests: wrong key, tampered payload covered
# - Empty signature edge case covered
# - ImportError when crypto missing covered

# Step 3 — Break It List
# - All R7 forgery scenarios covered (wrong key, tamper, empty sig)
"""

from __future__ import annotations

import pytest

from sm_governance.approval import ModelApproval
from tests.conftest import HAS_CRYPTOGRAPHY, skip_no_crypto

if HAS_CRYPTOGRAPHY:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )


@skip_no_crypto
def test_sign_verify_roundtrip() -> None:
    from sm_governance.signing import sign_approval, verify_approval

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    approval = ModelApproval(
        model_id="m1",
        weights_hash="abc",
        approved_by="alice",
    )
    sig = sign_approval(approval, private_key)
    assert isinstance(sig, str)
    assert len(sig) > 0

    approval.signature = sig
    assert verify_approval(approval, public_key) is True


@skip_no_crypto
def test_tamper_detection() -> None:
    from sm_governance.signing import sign_approval, verify_approval

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    approval = ModelApproval(
        model_id="m1",
        weights_hash="abc",
        approved_by="alice",
    )
    approval.signature = sign_approval(approval, private_key)

    # Tamper with model_id
    approval.model_id = "tampered"
    assert verify_approval(approval, public_key) is False


@skip_no_crypto
def test_wrong_key_fails() -> None:
    from sm_governance.signing import sign_approval, verify_approval

    key_a = Ed25519PrivateKey.generate()
    key_b = Ed25519PrivateKey.generate()

    approval = ModelApproval(
        model_id="m1",
        approved_by="alice",
    )
    approval.signature = sign_approval(approval, key_a)

    # Verify with wrong public key
    assert verify_approval(approval, key_b.public_key()) is False


@skip_no_crypto
def test_empty_signature_returns_false() -> None:
    from sm_governance.signing import verify_approval

    key = Ed25519PrivateKey.generate()
    approval = ModelApproval(model_id="m1", signature="")
    assert verify_approval(approval, key.public_key()) is False


def test_import_error_without_crypto() -> None:
    """Verify that helpful ImportError is raised when crypto is missing."""
    from sm_governance._compat import has_cryptography

    if has_cryptography():
        pytest.skip("cryptography is installed")

    from sm_governance.signing import sign_approval

    approval = ModelApproval(model_id="m1")
    with pytest.raises(ImportError, match="cryptography"):
        sign_approval(approval, None)
