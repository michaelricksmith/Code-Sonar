/**
 * AskSonarDrawer — global chat assistant on every screen (§2.4 screen 5).
 * Suggested questions, plain-language answers, citations to referenced
 * issues. Provider status shown honestly: env-configured default or BYOK
 * entry — never a dead "provider not configured" state.
 */

import { useEffect, useRef, useState } from "react";

import type { Finding } from "../api/analyzers";
import { askSonar } from "../api/askSonar";
import type { AiProvider } from "../api/askSonar";
import { copy } from "../copy";
import { issueCardTitle } from "../copy/issues";

interface ChatMessage {
  role: "user" | "sonar";
  text: string;
  citations?: string[];
}

interface AskSonarDrawerProps {
  open: boolean;
  onClose: () => void;
  scanId: string | null;
  repoLabel: string | null;
  findings: Finding[];
  providers: AiProvider[] | null;
  providersError: string | null;
  initialQuestion: string | null;
  onConsumeInitialQuestion: () => void;
  onOpenIssue: (finding: Finding) => void;
  providerName: string;
  apiKey: string;
  onProviderChange: (name: string) => void;
  onApiKeyChange: (key: string) => void;
}

const SUGGESTED = [
  "Explain this like I'm new",
  "Will this break my app?",
  "What should I fix first, and why?",
];

function findingById(findings: Finding[], id: string): Finding | undefined {
  return findings.find((f) => f.id === id || f.id.startsWith(id) || id.startsWith(f.id));
}

export function AskSonarDrawer({
  open,
  onClose,
  scanId,
  repoLabel,
  findings,
  providers,
  providersError,
  initialQuestion,
  onConsumeInitialQuestion,
  onOpenIssue,
  providerName,
  apiKey,
}: AskSonarDrawerProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const chatRef = useRef<HTMLDivElement>(null);

  const configured = providers?.find((p) => p.configured) ?? null;
  // Headers are only sent when the user explicitly picked a provider via BYOK.
  // Otherwise the server answers with its configured provider (or reports
  // honestly that none is configured) instead of rejecting a phantom default.
  const byokOpts = providerName ? { provider: providerName, apiKey: apiKey || undefined } : {};

  useEffect(() => {
    if (!open) return;
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight });
  }, [messages, open]);

  useEffect(() => {
    if (open && initialQuestion) {
      setInput(initialQuestion);
      onConsumeInitialQuestion();
    }
  }, [open, initialQuestion, onConsumeInitialQuestion]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  async function send(question: string): Promise<void> {
    const q = question.trim();
    if (!q || asking) return;
    if (!scanId) {
      setError("Run a scan first — Sonar grounds every answer in your actual code.");
      return;
    }
    setAsking(true);
    setError(null);
    setMessages((m) => [...m, { role: "user", text: q }]);
    setInput("");
    try {
      const res = await askSonar(
        { scanId, question: q },
        byokOpts,
      );
      setMessages((m) => [
        ...m,
        { role: "sonar", text: res.answer.answer, citations: res.answer.used_sources },
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setAsking(false);
    }
  }

  if (!open) return null;

  return (
    <>
      <div className="drawer-veil" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Ask Sonar">
        <div className="drawer-head">
          <div className="t"><span className="pulse" />Ask Sonar</div>
          <button className="drawer-close" onClick={onClose} aria-label="Close Ask Sonar">✕</button>
        </div>

        <div className="provider-line">
          {providersError ? (
            <><span className="pdot off" />Couldn&rsquo;t check AI providers — answers still grounded in your scan.</>
          ) : configured ? (
            <><span className="pdot" />AI ready · {configured.label}{configured.source === "env" ? " (configured)" : ""} · grounded in {repoLabel ?? "your repo"}</>
          ) : (
            <><span className="pdot off" />Coming Soon</>
          )}
        </div>

        <div className="chat" ref={chatRef}>
          {messages.length === 0 && (
            <div className="chat-welcome">
              <h3>{configured ? "Ask about your score, risks, or next fix." : "Sonar Chat is coming soon."}</h3>
              <p>
                {configured ? (
                  <>
                    Sonar answers from your actual scan — {findings.length} {findings.length === 1 ? copy.finding : copy.findings} on the board.
                    It can explain and plan fixes, but it can&rsquo;t silently change your score.
                  </>
                ) : (
                  <>
                    We&rsquo;re putting the finishing touches on Sonar Chat.
                    Your deterministic scan results above are ready now — no AI needed.
                  </>
                )}
              </p>
              {configured && (
                <div className="suggest-row" style={{ marginTop: 12 }}>
                  {SUGGESTED.map((s) => (
                    <button key={s} className="suggest" onClick={() => void send(s)} disabled={asking || !scanId}>
                      {s}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`msg ${m.role}`}>
              {m.text}
              {m.citations && m.citations.length > 0 && (
                <span className="cite">
                  Based on:{" "}
                  {m.citations.map((c, j) => {
                    const f = findingById(findings, c);
                    return (
                      <span key={j}>
                        {j > 0 && ", "}
                        {f ? (
                          <button className="link" style={{ fontSize: 12 }} onClick={() => onOpenIssue(f)}>
                            {issueCardTitle(f)}
                          </button>
                        ) : (
                          <span className="mono" style={{ fontSize: 12 }}>{c.slice(0, 24)}</span>
                        )}
                      </span>
                    );
                  })}
                </span>
              )}
            </div>
          ))}
          {asking && <div className="msg sonar">Thinking…</div>}
          {error && (
            <div className="notice warning" style={{ marginBottom: 0 }}>
              <b>Ask Sonar couldn&rsquo;t answer</b>{error}
            </div>
          )}
        </div>

        <div className="compose">
          <input
            className="input"
            placeholder={
              !configured
                ? "Sonar Chat is coming soon…"
                : scanId
                  ? "Ask about your code…"
                  : "Run a scan to ask Sonar…"
            }
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void send(input);
            }}
            disabled={!scanId || !configured}
            aria-label="Ask Sonar a question"
          />
          <button className="btn btn-primary" onClick={() => void send(input)} disabled={asking || !input.trim() || !scanId || !configured}>
            {asking ? "…" : "Ask"}
          </button>
        </div>
      </aside>
    </>
  );
}
