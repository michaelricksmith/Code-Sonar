# RICK Capability Upgrade Roadmap

Code Sonar was created, built, directed, and is owned by Michael Smith (GitHub: `michaelricksmith`). Copyright © 2026 Michael Smith. All rights reserved.

## Decision

The repositories below were researched on August 31, 2026. Michael Smith approved the first installation wave on September 1, 2026. That approval did not authorize credential access, publishing, destructive actions, paid services, or unrestricted execution permissions.

## Recommended repositories

| Priority | Capability | Repository | Stars observed | License | Intended RICK role | Recommendation |
|---:|---|---|---:|---|---|---|
| 1 | Browser automation and testing | [microsoft/playwright](https://github.com/microsoft/playwright) | 95,453 | Apache-2.0 | Tester | Install first for Code Sonar UI and browser workflow testing. |
| 2 | Security scanning | [aquasecurity/trivy](https://github.com/aquasecurity/trivy) | 37,721 | Apache-2.0 | Reviewer/Tester | Scan dependencies, repositories, secrets, configuration, and SBOMs. |
| 3 | Diagramming | [mermaid-js/mermaid](https://github.com/mermaid-js/mermaid) | 90,020 | MIT | Planner | Generate architecture, sequence, data-flow, and threat-model diagrams in Markdown. |
| 4 | Local summarization | [miso-belica/sumy](https://github.com/miso-belica/sumy) | 3,702 | Apache-2.0 | Researcher | Lightweight local summarization without recurring API-token cost. |
| 5 | Python debugging | [microsoft/debugpy](https://github.com/microsoft/debugpy) | 2,463 | MIT | Tester | Debug Python components through the Debug Adapter Protocol. |
| 6 | Node.js debugging | [microsoft/vscode-js-debug](https://github.com/microsoft/vscode-js-debug) | 1,967 | MIT | Tester | Debug JavaScript and Node.js processes through the Debug Adapter Protocol. |
| 7 | Rapid prototyping | [streamlit/streamlit](https://github.com/streamlit/streamlit) | 45,654 | Apache-2.0 | Builder | Build temporary internal dashboards and proof-of-concept tools. |
| 8 | Coding agent | [anomalyco/opencode](https://github.com/anomalyco/opencode) | 202,899 | MIT | Builder | Evaluate as an optional coding worker; confirm local-model compatibility before adoption. |
| 9 | AI observability | [langfuse/langfuse](https://github.com/langfuse/langfuse) | 34,013 | MIT core; enterprise directories separately licensed | Administrator | Consider only if RICK needs a persistent tracing and evaluation service. |
| 10 | Durable orchestration | [temporalio/temporal](https://github.com/temporalio/temporal) | 22,731 | MIT | Administrator | Defer; RICK's existing TaskFlow approach should be tested before adding a server platform. |
| 11 | GitHub automation | [cli/cli](https://github.com/cli/cli) | 46,091 | MIT | Main/Reviewer | Already installed and authenticated; configure scoped workflows instead of reinstalling. |
| 12 | Skill validation | [agent-ecosystem/skill-validator](https://github.com/agent-ecosystem/skill-validator) | 235 | MIT | Administrator | Validate custom RICK skills before enabling them. |

## Installation policy

1. Review the exact release or commit before installation; pin versions where practical.
2. Install one capability at a time and record files, services, environment changes, and rollback steps.
3. Keep execution isolated by role. Do not grant RICK/main unrestricted shell access.
4. Require explicit approval for credentials, authenticated writes, publishing, destructive actions, and new background services.
5. Verify each installation with a small end-to-end Code Sonar task before continuing.
6. Prefer local, free, and open-source operation. Do not introduce paid APIs without Michael Smith's explicit approval.

## Planned first installation wave

1. Playwright
2. Trivy
3. Mermaid
4. Sumy
5. Debugpy and VS Code JS Debug
6. Streamlit

OpenCode, Langfuse, and Temporal require separate resource and architecture reviews before installation.

## Installation record — September 1, 2026

| Capability | Installed version | Location / integration | Verification |
|---|---:|---|---|
| Playwright | 1.62.1 | `frontend` development dependency plus Chromium | Version check and real headless Chromium launch passed. |
| Trivy | 0.74.0 | `C:\Users\bookm\.openclaw\tools\trivy\0.74.0` | Official archive checksum verified; narrow read-only secret scan passed. |
| Mermaid CLI | 11.16.0 | `C:\Users\bookm\.openclaw\tools\mermaid-cli` | SVG render passed. |
| Sumy | 0.13.0 | Isolated RICK Python environment | Real two-sentence extractive summary passed after installing local `punkt_tab` data. |
| Debugpy | 1.8.21 | Isolated RICK Python environment | Version/import check passed. |
| VS Code JS Debug | 1.117.0 | Already bundled with installed VS Code | Built-in extension package version verified; replacement was unnecessary. |
| Streamlit | 1.62.0 | Isolated RICK Python environment | CLI version check passed. |

Python tools are isolated under `C:\Users\bookm\.openclaw\tools\rick-capabilities-python`. Stable command shims were added to the existing user npm command directory for Trivy, Mermaid, Sumy, Debugpy, and Streamlit.

OpenClaw skills were assigned by role without widening tool permissions:

- Planner: `diagram-maker`
- Builder: `diagram-maker`, `local-prototyping`
- Tester: `code-sonar-playwright`, `code-sonar-security`, `node-inspect-debugger`, `python-debugpy`, `local-prototyping`
- Researcher: `agent-reach`, `local-summarize`
- RICK/main remains a coordinator with no direct execution skill.

The OpenClaw gateway was restarted and returned healthy. Execution-capable agents retain their existing approval gates.

## Rollback

- Playwright: remove `@playwright/test` from `frontend/package.json`, restore the lockfile through normal version control, and remove its browser cache only if no other project uses it.
- Trivy: remove its command shim, then remove `C:\Users\bookm\.openclaw\tools\trivy\0.74.0`.
- Mermaid: remove its command shim, then remove `C:\Users\bookm\.openclaw\tools\mermaid-cli`.
- Sumy, Debugpy, and Streamlit: remove their command shims, then remove the isolated `rick-capabilities-python` environment.
- VS Code JS Debug: no rollback is needed because the approved version was already a built-in VS Code component.
- OpenClaw integration: restore the pre-change skill allowlists from the configuration backup or set the affected agent `skills` arrays back to their prior values, validate, and restart the gateway.

## Research note

The public `anthropics/skills` repository had substantially more stars than the selected skill validator, but GitHub did not expose a single repository-wide license during review. Treat it as reference material and verify licensing per directory before reuse.
