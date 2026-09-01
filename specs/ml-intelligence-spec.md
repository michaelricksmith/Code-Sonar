# Code Sonar ML Intelligence Specification

**Created, built, and owned by Michael Smith (GitHub: `michaelricksmith`). Copyright © 2026 Michael Smith. All rights reserved.**

**Status:** ML-0 baseline
**Branch:** `feature/ml-intelligence-layer`
**Principle:** Machine learning augments Code Sonar; it does not replace the deterministic scoring engine.

## 1. Product invariant

The deterministic Code Sonar score remains the authoritative technical-debt score. ML outputs are advisory intelligence: probability, classification, similarity, confidence, prioritization, explanation, and expected remediation outcome.

A model failure, unavailable artifact, missing training data, or low-confidence prediction must never prevent a repository scan or change the deterministic score.

## 2. Initial model suite

| Model | Primary task | Required output |
|---|---|---|
| Logistic Regression | Explainable debt-risk probability baseline | probability, class, confidence, feature contributions, model version |
| Decision Tree | Human-readable risk rules and decision paths | class, confidence, decision path, model version |
| Support Vector Machine | Higher-dimensional risk classification | class, confidence/calibrated score, model version |
| K-Nearest Neighbors | Historical similarity / institutional memory | nearest cases, distance/similarity, historical outcomes, model version |

Different prediction tasks may have different champion models. Model outputs must not be averaged merely because multiple algorithms exist.

## 3. ML package boundary

Planned backend structure:

```text
app/ml/
  features/
    schema.py
    extractor.py
  datasets/
    builder.py
    labels.py
  models/
    logistic.py
    decision_tree.py
    svm.py
    knn.py
  evaluation/
    metrics.py
    registry.py
  prediction/
    service.py
  outcomes/
    schema.py
```

The ML package consumes normalized scan/history data and future Git/remediation signals. It must not import internal scoring constants to mutate or recalculate the Code Sonar score.

## 4. Feature groups

### 4.1 Scan-level deterministic features
- score
- total debt points
- finding count
- category scores
- findings by category
- severity distribution
- source/test/fixture distribution
- hotspot aggregates
- drift aggregates when a prior scan exists

### 4.2 Finding/file structure features
- cyclomatic complexity
- cognitive complexity when available
- function/class/file size
- nesting depth
- duplication signals
- dependency count/depth
- coupling/cohesion signals when available

### 4.3 Git/change-history features
- commit frequency
- churn
- author count
- ownership concentration
- file age
- time since last modification
- bug-fix frequency
- revert frequency

### 4.4 Quality/security/repository-health features
- testing-debt signals
- test coverage when available
- lint/type/build failures when available
- vulnerability/security finding counts
- dependency age and update frequency
- documentation signals
- CI stability

### 4.5 Finding-history features
- finding age
- recurrence count
- fixed/reintroduced state
- suppression/ignore state when supported
- remediation attempts
- time to remediation

### 4.6 Business-impact features
These are optional explicit annotations, never inferred as fact without evidence:
- critical-path indicator
- production exposure
- user-facing component
- API exposure
- database interaction
- authentication/authorization relevance

### 4.7 Remediation outcome features
- recommendation accepted/rejected
- remediation attempted
- fix succeeded/failed
- build passed/failed
- tests passed/failed
- finding resolved/persisted/reintroduced
- deterministic score delta
- debt delta
- regression introduced
- time to resolution

## 5. Feature schema and versioning

Every model input must declare a `feature_schema_version`. Feature vectors must be serialized in a stable, ordered representation. Changing the meaning, scaling, or inclusion of a feature requires a new schema version.

Training and prediction must use the same feature schema. A model artifact trained on an incompatible schema must be rejected rather than silently coerced.

## 6. Labels and ground truth

Training labels are tiered by trust:

1. **Proxy labels** — derived from deterministic Code Sonar rules for bootstrapping only.
2. **Historical Git outcomes** — bug-fix commits, reverts, refactors, recurrence, time-to-resolution.
3. **Developer interactions** — accepted/rejected recommendation and explicit priority feedback.
4. **Observed remediation outcomes** — build/test/rescan results after a remediation attempt.
5. **Production-quality labels** — accumulated outcome data with sufficient coverage and validation.

Proxy labels must be marked as proxy labels in dataset metadata. They must not be represented as observed ground truth.

## 7. Dataset safety and leakage controls

- Train/test splits must be repository-aware when evaluating generalization across repositories.
- Rows from the same finding lineage must not leak across train/test boundaries.
- Future information must not be included in features used to predict an earlier outcome.
- Repository/customer data must remain isolated.
- Persisted evidence remains redacted before it reaches ML datasets.
- Secrets and raw credentials are forbidden model features.

## 8. Evaluation and champion selection

Classification evaluation should include, as applicable:
- precision
- recall
- F1
- ROC-AUC
- confusion matrix
- probability calibration
- baseline comparison

KNN/similarity evaluation should include retrieval relevance and outcome consistency, not classification metrics alone.

A registry record should capture:
- model id/version
- algorithm
- prediction task
- feature schema version
- dataset version
- training timestamp
- metrics
- champion/challenger status
- artifact reference

A model is promoted only if it beats the current baseline on the declared task without violating calibration, leakage, or reproducibility gates.

## 9. Prediction contract

ML predictions should return structured metadata such as:

```json
{
  "task": "debt_risk",
  "prediction": "high",
  "probability": 0.87,
  "confidence": 0.82,
  "model_id": "debt-risk-logreg",
  "model_version": "1.0.0",
  "feature_schema_version": "1.0",
  "top_contributors": ["high_churn", "low_test_coverage", "high_complexity"],
  "advisory": true
}
```

ML responses must explicitly identify themselves as advisory. Ask Sonar must distinguish deterministic findings/scoring from modeled predictions.

## 10. Planned API surface

- `POST /api/ml/predict`
- `GET /api/ml/models`
- `GET /api/ml/model-performance`
- `GET /api/ml/similar-findings/{finding_id}`

These endpoints are additive. Existing `/api/scan`, `/api/history`, `/api/drift`, `/api/hotspots`, and deterministic scoring behavior remain stable.

## 11. Ask Sonar integration

Ask Sonar may consume deterministic scan data plus ML prediction context to answer:
- Why is this finding/repository risky?
- Which factors most influenced the prediction?
- How confident is the model?
- What historical cases are most similar?
- What happened after similar remediations?
- Which remediation is most likely to succeed?

Ask Sonar must identify uncertainty and must not present a modeled probability as a deterministic fact.

## 12. Closed learning loop

```text
scan
  -> deterministic findings + score
  -> feature extraction
  -> ML prediction
  -> Ask Sonar explanation/recommendation
  -> remediation attempt
  -> build/tests
  -> rescan
  -> outcome record
  -> versioned training dataset
  -> controlled retraining/evaluation
```

Retraining is initially deliberate and versioned. No production model may silently retrain or promote itself.

## 13. Implementation checkpoints

- **ML-0:** architecture/specification + package boundary
- **ML-1:** feature schema + deterministic scan feature extraction + dataset-row contract
- **ML-2:** Logistic Regression baseline + evaluation
- **ML-3:** Decision Tree + SVM + KNN
- **ML-4:** evaluation framework + model registry/champion selection
- **ML-5:** prediction/model/similarity APIs
- **ML-6:** Ask Sonar integration
- **ML-7:** remediation outcome recording + closed feedback loop

## 14. Non-negotiable acceptance gates

- Existing deterministic scan/score tests remain unchanged and green.
- ML failure cannot fail `/api/scan`.
- Same scan record + same feature schema produces byte-identical feature output.
- Model and feature schema versions are always exposed with predictions.
- No raw secrets enter datasets or predictions.
- No cross-repository train/test leakage in generalization evaluation.
- No automatic model promotion without recorded evaluation gates.
- Existing API behavior remains backward compatible unless separately versioned.
