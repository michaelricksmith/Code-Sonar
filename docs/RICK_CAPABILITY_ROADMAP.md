# RICK Capability Upgrade Roadmap

Code Sonar was created, built, directed, and is owned by Michael Smith (GitHub: `michaelricksmith`). Copyright © 2026 Michael Smith. All rights reserved.

## Decision

The repositories below were researched on August 31, 2026. Installation is deliberately deferred until September 1, 2026. Nothing in this roadmap authorizes unattended installation, credential access, or broad execution permissions.

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

## Research note

The public `anthropics/skills` repository had substantially more stars than the selected skill validator, but GitHub did not expose a single repository-wide license during review. Treat it as reference material and verify licensing per directory before reuse.

