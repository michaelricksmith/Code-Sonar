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

The blinded pilot workflow is specified in `REVIEWER_RUBRIC.md`. Start from
`pilot-manifest.template.json`; `pilot.py validate` validates metadata and
`pilot.py generate` creates independent packets. Both explicitly report that
accuracy is not validated. `pilot.py evaluate` refuses metrics until every case
has two finalized independent labels and finalized adjudication. No command
fetches repositories, invents labels, or changes scoring.

After two reviewers finalize a case, `pilot.py adjudicate LABEL_A LABEL_B
--output labels/csb-NNN-adjudication.json` creates a draft form embedding both
opinions. Complete its resolution fields, mark it finalized, and reference it as
`adjudicated_label_file` in the case manifest.

`corpus-candidates.json` is the operator-only provenance manifest. It pins
eight public candidates to exact commits and license files and leaves four
controlled-fixture slots explicitly unpopulated. Never include this
identity-bearing file in blinded reviewer packets.
