# Calibration Pilot Reviewer Rubric v1

This protocol measures Code Sonar; it does not train reviewers to agree with it.
Repositories must be approved for review and pinned to the exact commit in the
metadata manifest. The coordinator assigns non-identifying pseudonyms such as
`reviewer-01`. Identity mappings stay outside the repository.

## Blinding and independence

Reviewers inspect the pinned repository and tests without seeing Code Sonar's
score, grade, category scores, another review, or adjudication. Do not discuss a
case until both repository labels are finalized. Record outside research and any
unavailable build/test evidence. Choose `insufficient_evidence: true` instead of
guessing when the repository cannot be meaningfully inspected.

## Repository label

Assess the code as it exists at the pinned commit:

- Grade A: low material debt; safe routine evolution.
- Grade B: contained debt; ordinary maintenance risk.
- Grade C: meaningful debt requiring planned correction.
- Grade D: severe, pervasive debt that regularly obstructs safe change.
- Grade F: critical systemic risk; normal change is unsafe or unreliable.

Also assign ordinal health 1 (worst) through 10 (best), each applicable category
1 through 10, confidence from 0 through 1, and a concise evidence-based rationale.
The grade is a holistic judgment, not a conversion from the ordinal number.

## Finding label

Packets sample up to two findings from every analyzer × reported-severity cell.
Within each cell, SHA-256 ordering of the opaque finding ID prevents coordinator
selection. For each sampled finding choose:

- `true_positive`: the reported condition exists at the pinned commit.
- `false_positive`: the reported condition does not exist or the rule is inapplicable.
- `uncertain`: available evidence cannot support either conclusion.

Assign expert severity (`info`, `warning`, `error`, or `critical`) only when the
condition is understood. Set it to null with `insufficient_evidence: true` when
the packet and permitted repository inspection are inadequate. Record confidence
and rationale. Finding IDs are opaque; packets contain no source, path, message,
symbol, suggestion, repository name, URL, or Code Sonar score.

## Finalization and adjudication

Finalized files are immutable inputs. A coordinator verifies at least two unique
reviewer pseudonyms per case, then creates adjudication only after both are final.
The adjudication artifact embeds every independent grade, ordinal/category rating,
and confidence. It must retain the set/range of disagreements and explain the
resolution; it must never overwrite the original labels. Accuracy evaluation
refuses draft, insufficient, single-reviewer, or unadjudicated cases.

No pilot result authorizes changing scoring weights or grade thresholds. Proposed
calibration changes require a separately reviewed benchmark report and a new
scoring version when score semantics change.
