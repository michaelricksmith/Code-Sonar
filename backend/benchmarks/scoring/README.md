# Scoring calibration benchmark

This versioned framework compares frozen Code Sonar result JSON with blinded,
independent expert labels. It deliberately contains no invented labels and does
not fetch repositories. Add approved cases to `manifest.json`, store analyzer
output in `findings/`, and store adjudicated labels in `labels/`.

Capture only complete scan responses with:

`python capture.py INPUT_SCAN_JSON csb-001 EXPECTED_SCORING_VERSION OUTPUT_JSON`

Capture removes repository identity, paths, source evidence, messages, symbols,
and suggestions. The output contains a canonical SHA-256 hash. Keep source and
reviewer access separate; never add customer source or repository claims here.

Run `python evaluate.py manifest.json` after cases contain finalized blinded
labels. The report includes exact and within-band grade agreement, quadratic
weighted kappa, expert-ordinal Spearman correlation, per-analyzer precision,
severity agreement, fixed-seed bootstrap confidence intervals, and breakdowns
by declared stratum. Benchmark releases must be frozen in a new version
directory before scoring calibration changes are proposed.
