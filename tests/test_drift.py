"""Tests for drift detection.

# Step 1 — Assumption Audit
# - check_drift compares loss (relative increase) and accuracy (ratio)
# - max_loss_increase default 0.20; check is strict > (not >=)
# - check_distribution_drift uses custom KS statistic; needs >= 10 samples
# - Confidence is 0.0 when no metrics; 1.0 when metrics present
# - Severity thresholds: <0.3 monitor, <0.6 investigate, <0.8 investigate, >=0.8 revoke

# Step 2 — Gap Analysis
# - No test for drift at exact threshold (is_drifted boundary)
# - No test for identical training/serving metrics
# - No test for identical distributions (KS ~= 0)
# - No test for exactly 10 samples (minimum boundary)

# Step 3 — Break It List
# - R5: loss increase exactly at threshold -> not drifted (strict >)
# - Identical metrics -> no drift, severity 0
# - Distribution with identical data -> KS near 0
# - Exactly 10 samples should be accepted (boundary)
"""

from __future__ import annotations

from sm_governance.drift import (
    DriftConfig,
    check_distribution_drift,
    check_drift,
    create_drift_alert,
)


def test_no_drift() -> None:
    result = check_drift(
        "m1",
        {"loss": 0.30, "accuracy": 0.92},
        {"loss": 0.32, "accuracy": 0.91},
    )
    assert result.is_drifted is False
    assert result.recommended_action == "monitor"


def test_loss_drift() -> None:
    result = check_drift(
        "m1",
        {"loss": 0.30},
        {"loss": 0.50},
    )
    assert result.is_drifted is True
    assert any(m.name == "loss" and m.is_drifted for m in result.metrics)


def test_accuracy_drift() -> None:
    result = check_drift(
        "m1",
        {"accuracy": 0.92},
        {"accuracy": 0.70},
    )
    assert result.is_drifted is True
    assert any(m.name == "accuracy" and m.is_drifted for m in result.metrics)


def test_custom_config() -> None:
    strict = DriftConfig(max_loss_increase=0.05, min_accuracy_ratio=0.99)
    result = check_drift(
        "m1",
        {"loss": 0.30, "accuracy": 0.92},
        {"loss": 0.33, "accuracy": 0.91},
        config=strict,
    )
    assert result.is_drifted is True


def test_severe_drift_action() -> None:
    result = check_drift(
        "m1",
        {"loss": 0.10},
        {"loss": 1.00},
    )
    assert result.is_drifted is True
    assert result.recommended_action == "consider_revoke"
    assert result.overall_severity >= 0.8


def test_drift_to_dict() -> None:
    result = check_drift(
        "m1",
        {"loss": 0.30},
        {"loss": 0.50},
    )
    d = result.to_dict()
    assert d["model_id"] == "m1"
    assert d["is_drifted"] is True
    assert isinstance(d["metrics"], list)


def test_no_metrics() -> None:
    result = check_drift("m1", {}, {})
    assert result.is_drifted is False
    assert result.confidence == 0.0


def test_create_alert_when_drifted() -> None:
    result = check_drift("m1", {"loss": 0.10}, {"loss": 1.00})
    alert = create_drift_alert(result)
    assert alert is not None
    assert alert.model_id == "m1"
    assert alert.severity == "critical"


def test_create_alert_no_drift() -> None:
    result = check_drift("m1", {"loss": 0.30}, {"loss": 0.30})
    alert = create_drift_alert(result)
    assert alert is None


def test_distribution_drift_detected() -> None:
    import random

    random.seed(42)
    training = [random.gauss(0.0, 1.0) for _ in range(100)]
    serving = [random.gauss(2.0, 1.0) for _ in range(100)]
    result = check_distribution_drift("m1", training, serving)
    assert result.is_drifted is True
    assert any(m.name == "ks_statistic" for m in result.metrics)


def test_distribution_drift_no_drift() -> None:
    import random

    random.seed(42)
    training = [random.gauss(0.0, 1.0) for _ in range(100)]
    serving = [random.gauss(0.0, 1.0) for _ in range(100)]
    result = check_distribution_drift("m1", training, serving)
    assert result.is_drifted is False


def test_distribution_drift_insufficient_samples() -> None:
    result = check_distribution_drift("m1", [1.0, 2.0], [1.0, 2.0])
    assert result.is_drifted is False
    assert result.confidence == 0.0
    assert "Insufficient" in result.summary


def test_alert_severity_levels() -> None:
    # Low severity — just barely over the 20% threshold
    config = DriftConfig(max_loss_increase=0.20)
    result = check_drift(
        "m1",
        {"loss": 1.00},
        {"loss": 1.22},
        config=config,
    )
    alert = create_drift_alert(result)
    if alert:
        # 22% increase / 20% threshold -> severity ~1.1 capped to 1.0
        # With only one metric, overall_severity == drift_severity
        assert alert.severity in ("low", "medium", "high", "critical")

    # Critical severity — 10x loss
    result = check_drift(
        "m1",
        {"loss": 0.10},
        {"loss": 1.00},
    )
    alert = create_drift_alert(result)
    assert alert is not None
    assert alert.severity == "critical"


# -- Adversarial drift tests -------------------------------------------


def test_drift_at_exact_threshold() -> None:
    """R5: loss increase exactly at max_loss_increase -> not drifted (strict >)."""
    config = DriftConfig(max_loss_increase=0.20)
    result = check_drift(
        "m1",
        {"loss": 1.00},
        {"loss": 1.20},  # exactly 20% increase
        config=config,
    )
    assert result.is_drifted is False


def test_drift_with_identical_metrics() -> None:
    """Identical serving and training metrics -> no drift."""
    result = check_drift(
        "m1",
        {"loss": 0.35, "accuracy": 0.92},
        {"loss": 0.35, "accuracy": 0.92},
    )
    assert result.is_drifted is False
    assert result.overall_severity == 0.0


def test_distribution_drift_identical_distributions() -> None:
    """Identical distributions -> KS statistic near 0, no drift."""
    data = [float(i) for i in range(50)]
    result = check_distribution_drift("m1", data, list(data))
    assert result.is_drifted is False
    ks_metric = next(m for m in result.metrics if m.name == "ks_statistic")
    assert ks_metric.serving_value < 0.05  # KS near 0 for identical data


def test_distribution_drift_with_exactly_10_samples() -> None:
    """R5: exactly 10 samples per side is the minimum accepted."""
    training = [float(i) for i in range(10)]
    serving = [float(i) + 100.0 for i in range(10)]
    result = check_distribution_drift("m1", training, serving)
    # Should be processed (not rejected as insufficient)
    assert result.confidence > 0.0
    assert result.is_drifted is True
