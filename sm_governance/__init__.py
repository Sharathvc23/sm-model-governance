"""NANDA Model Governance — three-plane ML governance with cryptographic approvals.

Enforces that no single execution path can train, approve, AND deploy
a model.  Three isolated planes — Training, Governance, Serving — with
Ed25519 cryptographic signatures, time-bounded approvals, environment /
scope constraints, M-of-N multi-approver quorum, drift detection, and
revocation.
"""

from __future__ import annotations

from sm_governance._types import ApprovalStatus, DriftSeverity
from sm_governance.approval import (
    ApprovalStore,
    ModelApproval,
)
from sm_governance.contracts import (
    AdapterRegistry,
    EvidenceLedger,
    ModelCard,
    ModelValidator,
    ServingEndpoint,
    TrainingResult,
    ValidationResult,
)
from sm_governance.coordinator import GovernanceCoordinator
from sm_governance.drift import (
    DriftAlert,
    DriftCheckResult,
    DriftConfig,
    DriftMetric,
    check_distribution_drift,
    check_drift,
    create_drift_alert,
)
from sm_governance.promotion import PromotionResult, promote_model
from sm_governance.signing import sign_approval, verify_approval
from sm_governance.stores.memory import InMemoryApprovalStore
from sm_governance.training import TrainingOutput

# Optional bridge to integrity layer
try:
    from sm_governance.protocol import (
        approval_to_integrity_facts,
        create_provenance_with_approval,
    )
except ImportError:
    # Functions not available without integrity extra
    approval_to_integrity_facts = None  # type: ignore
    create_provenance_with_approval = None  # type: ignore

__version__ = "0.2.0"

__all__ = [
    # coordinator
    "GovernanceCoordinator",
    # enums
    "ApprovalStatus",
    "DriftSeverity",
    # approval
    "ApprovalStore",
    "ModelApproval",
    # training
    "TrainingOutput",
    # signing
    "sign_approval",
    "verify_approval",
    # promotion
    "PromotionResult",
    "promote_model",
    # drift
    "DriftAlert",
    "DriftCheckResult",
    "DriftConfig",
    "DriftMetric",
    "check_distribution_drift",
    "check_drift",
    "create_drift_alert",
    # stores
    "InMemoryApprovalStore",
    # contracts
    "AdapterRegistry",
    "EvidenceLedger",
    "ModelCard",
    "ModelValidator",
    "ServingEndpoint",
    "TrainingResult",
    "ValidationResult",
    # protocol bridge (optional)
    "approval_to_integrity_facts",
    "create_provenance_with_approval",
]
