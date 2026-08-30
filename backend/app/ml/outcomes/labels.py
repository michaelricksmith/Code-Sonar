"""Convert observed remediation outcomes into higher-trust supervised labels."""

from __future__ import annotations

from app.ml.datasets.schema import LabelProvenance, LabelTrustTier
from app.ml.outcomes.schema import RemediationOutcome


def remediation_success_label(outcome: RemediationOutcome) -> LabelProvenance:
    """Create a binary supervised label from an observed remediation result."""
    return LabelProvenance(
        task="remediation_success",
        value="1" if outcome.successful else "0",
        trust_tier=LabelTrustTier.REMEDIATION_OUTCOME,
        source=f"remediation_outcome:{outcome.outcome_id}",
        observed_at=outcome.attempted_at,
    )
