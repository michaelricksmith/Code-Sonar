# Ask Sonar with Ollama

**Part of Code Sonar, created, built, and owned by Michael Smith (GitHub: `michaelricksmith`). Copyright © 2026 Michael Smith. All rights reserved.**

Ask Sonar can use a local Ollama model while keeping Code Sonar's deterministic score authoritative.

## Requirements

- Code Sonar running locally
- Ollama running locally
- A pulled model such as `llama3.1:8b`

No API key is required.

## Enable Ollama

Set these environment variables before starting the Code Sonar backend:

```text
CODE_SONAR_ASK_PROVIDER=ollama
CODE_SONAR_OLLAMA_MODEL=llama3.1:8b
CODE_SONAR_OLLAMA_BASE_URL=http://127.0.0.1:11434
CODE_SONAR_OLLAMA_TIMEOUT_SECONDS=45
```

Only `CODE_SONAR_ASK_PROVIDER=ollama` is required. The other values shown above are the defaults.

If `CODE_SONAR_ASK_PROVIDER` is unset, Ask Sonar has no text-generation provider and `/api/ask-sonar/ask` returns a controlled `503` response.

## Verify configuration

```text
GET /api/ask-sonar/status
```

Example configured response:

```json
{
  "configured": true,
  "provider": "ollama",
  "model": "llama3.1:8b",
  "network_checked": false
}
```

The status endpoint does not contact Ollama. The first network call occurs only when an Ask Sonar question is submitted.

## Ask a grounded question

Ask Sonar works from an already-persisted Code Sonar scan:

```text
POST /api/ask-sonar/ask
```

Example body:

```json
{
  "scan_id": "<stored-scan-id>",
  "question": "Why is this codebase graded B?"
}
```

The provider receives a sanitized grounding bundle containing authoritative deterministic scan facts plus optional advisory ML evidence. It does not receive direct filesystem, repository, or scanner access.

## Grounding rules

- The deterministic Code Sonar score and grade remain authoritative.
- ML prediction and historical similarity are advisory only.
- The model may only declare sources listed in `allowed_sources`.
- If the provider claims a source that was unavailable, Code Sonar rejects the generated answer.
- Ask Sonar never trains a model, runs a repository scan, or changes the score while answering a question.

## Local privacy boundary

With the default Ollama URL (`127.0.0.1`), the generated context stays on the local machine. Changing `CODE_SONAR_OLLAMA_BASE_URL` changes that deployment boundary, so operators should treat non-local endpoints as an explicit trust decision.
