# Scoring calibration benchmark

This versioned framework compares frozen Code Sonar result JSON with blinded,
independent expert labels. It deliberately contains no invented labels and does
not fetch repositories. Add approved cases to `manifest.json`, store analyzer
output in `findings/`, and store adjudicated labels in `labels/`.

Run `python evaluate.py manifest.json` after cases contain both `actual_grade`
and `expert_grade`. The report includes exact-grade agreement, agreement within
one grade band, and Spearman rank correlation. Benchmark releases must be frozen
in a new version directory before scoring calibration changes are proposed.
