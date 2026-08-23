import React, { useState } from 'react';
import {
  X,
  Copy,
  Check,
  ExternalLink,
  GitCommit,
  User,
  Clock,
  Code2,
  Sparkles,
  ShieldAlert,
  Layers,
  ArrowRight,
  Send,
  MessageSquare,
  FileCode,
  Share2,
} from 'lucide-react';
import { Finding, FindingStatus } from '../../types';
import { SeverityBadge, CategoryBadge } from './RiskBadge';

interface FindingDrawerProps {
  finding: Finding | null;
  onClose: () => void;
  onUpdateStatus: (id: string, status: FindingStatus) => void;
}

export const FindingDrawer: React.FC<FindingDrawerProps> = ({
  finding,
  onClose,
  onUpdateStatus,
}) => {
  const [copied, setCopied] = useState(false);
  const [activeTab, setActiveTab] = useState<'details' | 'remediation' | 'sarif'>('remediation');
  const [triageNote, setTriageNote] = useState('');
  const [notes, setNotes] = useState<{ author: string; time: string; text: string }[]>([
    {
      author: 'Devon Kowalski',
      time: '2 hours ago',
      text: 'Verified payload during staging smoke test. Affects tenant search cursor pagination.',
    },
  ]);
  const [fixApplied, setFixApplied] = useState(false);

  if (!finding) return null;

  const handleCopyCode = () => {
    navigator.clipboard.writeText(finding.suggestedFix || finding.codeSnippet);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleAddNote = (e: React.FormEvent) => {
    e.preventDefault();
    if (!triageNote.trim()) return;
    setNotes([
      ...notes,
      {
        author: 'You (Current Reviewer)',
        time: 'Just now',
        text: triageNote.trim(),
      },
    ]);
    setTriageNote('');
  };

  const sarifPayload = JSON.stringify(
    {
      version: '2.1.0',
      $schema: 'https://schemastore.azurewebsites.net/schemas/v2.1.0/sarif-schema.json',
      runs: [
        {
          tool: {
            driver: {
              name: 'CodeSonar',
              version: '2.4.0',
              rules: [{ id: finding.ruleId, name: finding.title }],
            },
          },
          results: [
            {
              ruleId: finding.ruleId,
              level: finding.severity === 'critical' ? 'error' : 'warning',
              message: { text: finding.description },
              locations: [
                {
                  physicalLocation: {
                    artifactLocation: { uri: finding.filePath },
                    region: {
                      startLine: finding.lineRange[0],
                      endLine: finding.lineRange[1],
                    },
                  },
                },
              ],
            },
          ],
        },
      ],
    },
    null,
    2
  );

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/60 z-40 backdrop-blur-[1px] transition-opacity"
        onClick={onClose}
      />

      {/* Drawer */}
      <div className="fixed top-0 right-0 bottom-0 w-full max-w-2xl bg-[#151A21] border-l border-[#2A3441] z-50 flex flex-col shadow-2xl overflow-hidden animate-in slide-in-from-right duration-200">
        {/* Header */}
        <div className="p-4 border-b border-[#2A3441] bg-[#1B222C]/60 flex items-start justify-between">
          <div className="space-y-1.5 pr-4">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-mono text-xs text-[#3F6B8F] font-bold bg-[#0E1116] px-2 py-0.5 rounded border border-[#2A3441]">
                {finding.id}
              </span>
              <span className="font-mono text-xs text-[#9CA6B2]">
                {finding.ruleId}
              </span>
              <SeverityBadge severity={finding.severity} size="sm" />
              <CategoryBadge category={finding.category} />
              {finding.cwe && (
                <span className="font-mono text-[11px] text-[#E7E9EC] bg-[#0E1116] px-1.5 py-0.5 rounded border border-[#2A3441]">
                  {finding.cwe}
                </span>
              )}
            </div>
            <h2 className="text-sm font-semibold text-[#E7E9EC] leading-snug">
              {finding.title}
            </h2>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-[#9CA6B2] hover:text-[#E7E9EC] hover:bg-[#1B222C] transition-colors shrink-0"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Action / Status Bar */}
        <div className="px-4 py-2 bg-[#0E1116] border-b border-[#2A3441] flex items-center justify-between text-xs font-mono">
          <div className="flex items-center gap-2">
            <span className="text-[#9CA6B2]">Status:</span>
            <select
              value={finding.status}
              onChange={(e) => onUpdateStatus(finding.id, e.target.value as FindingStatus)}
              className="bg-[#151A21] border border-[#2A3441] text-[#E7E9EC] rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-[#3F6B8F]"
            >
              <option value="open">Open (Unresolved)</option>
              <option value="in_triage">In Triage</option>
              <option value="suppressed">Suppressed / Accepted Risk</option>
              <option value="resolved">Resolved</option>
            </select>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                alert(`Jira ticket created: ENG-${Math.floor(1000 + Math.random() * 9000)} for ${finding.id}`);
              }}
              className="px-2 py-1 rounded bg-[#1B222C] border border-[#2A3441] text-[#9CA6B2] hover:text-[#E7E9EC] hover:border-[#3F6B8F] transition-colors"
            >
              Create Issue
            </button>
            <button
              onClick={handleCopyCode}
              className="flex items-center gap-1 px-2.5 py-1 rounded bg-[#3F6B8F] text-[#E7E9EC] font-semibold hover:bg-[#4D7FA8] transition-colors"
            >
              {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
              <span>{copied ? 'Copied' : 'Copy Patch'}</span>
            </button>
          </div>
        </div>

        {/* Content Tabs */}
        <div className="flex border-b border-[#2A3441] bg-[#151A21] px-4">
          <button
            onClick={() => setActiveTab('remediation')}
            className={`px-3 py-2 text-xs font-mono border-b-2 font-medium transition-colors ${
              activeTab === 'remediation'
                ? 'border-[#3F6B8F] text-[#E7E9EC]'
                : 'border-transparent text-[#9CA6B2] hover:text-[#E7E9EC]'
            }`}
          >
            Remediation & Diff
          </button>
          <button
            onClick={() => setActiveTab('details')}
            className={`px-3 py-2 text-xs font-mono border-b-2 font-medium transition-colors ${
              activeTab === 'details'
                ? 'border-[#3F6B8F] text-[#E7E9EC]'
                : 'border-transparent text-[#9CA6B2] hover:text-[#E7E9EC]'
            }`}
          >
            Impact & Metadata
          </button>
          <button
            onClick={() => setActiveTab('sarif')}
            className={`px-3 py-2 text-xs font-mono border-b-2 font-medium transition-colors ${
              activeTab === 'sarif'
                ? 'border-[#3F6B8F] text-[#E7E9EC]'
                : 'border-transparent text-[#9CA6B2] hover:text-[#E7E9EC]'
            }`}
          >
            SARIF Export
          </button>
        </div>

        {/* Body content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4 font-mono text-xs">
          {activeTab === 'remediation' && (
            <div className="space-y-4">
              {/* Description */}
              <div className="p-3 rounded-md bg-[#1B222C] border border-[#2A3441] text-[#9CA6B2] leading-relaxed font-sans text-xs">
                <span className="font-semibold text-[#E7E9EC] block mb-1">Impact Analysis:</span>
                {finding.description}
              </div>

              {/* Code comparison / snippet */}
              <div className="space-y-2">
                <div className="flex items-center justify-between text-[11px] text-[#9CA6B2]">
                  <span className="flex items-center gap-1.5 text-[#E7E9EC]">
                    <FileCode className="w-3.5 h-3.5 text-[#3F6B8F]" />
                    {finding.filePath}:{finding.lineRange[0]}-{finding.lineRange[1]}
                  </span>
                  <span>Commit {finding.commitHash}</span>
                </div>

                <div className="rounded-md border border-[#2A3441] bg-[#0E1116] overflow-hidden">
                  <div className="px-3 py-1.5 bg-[#1B222C] border-b border-[#2A3441] text-[10px] text-[#E07A7A] flex items-center justify-between">
                    <span>Vulnerable Source (Current AST)</span>
                    <span>Lines {finding.lineRange[0]}-{finding.lineRange[1]}</span>
                  </div>
                  <pre className="p-3 text-[11px] text-[#E7E9EC] overflow-x-auto whitespace-pre leading-relaxed font-mono">
                    {finding.codeSnippet}
                  </pre>
                </div>

                {finding.suggestedFix && (
                  <div className="rounded-md border border-[#4F8A73]/40 bg-[#0E1116] overflow-hidden">
                    <div className="px-3 py-1.5 bg-[#4F8A73]/15 border-b border-[#4F8A73]/30 text-[10px] text-[#7CC4A8] flex items-center justify-between">
                      <span className="flex items-center gap-1.5">
                        <Sparkles className="w-3 h-3 text-[#4F8A73]" />
                        Suggested Remediation
                      </span>
                      <span>Verified Pattern</span>
                    </div>
                    <pre className="p-3 text-[11px] text-[#7CC4A8] overflow-x-auto whitespace-pre leading-relaxed font-mono">
                      {finding.suggestedFix}
                    </pre>
                  </div>
                )}
              </div>

              {/* One click apply */}
              {finding.suggestedFix && (
                <div className="p-3 rounded-md bg-[#1B222C] border border-[#2A3441] flex items-center justify-between">
                  <div>
                    <div className="text-xs font-semibold text-[#E7E9EC]">Create Automated Remediation PR</div>
                    <div className="text-[11px] text-[#9CA6B2] font-sans">
                      Spawns a branch with verified patch and runs CI test suite.
                    </div>
                  </div>
                  <button
                    onClick={() => setFixApplied(true)}
                    disabled={fixApplied}
                    className={`px-3 py-1.5 rounded text-xs font-mono font-semibold transition-all ${
                      fixApplied
                        ? 'bg-[#4F8A73] text-[#0E1116]'
                        : 'bg-[#3F6B8F] text-[#E7E9EC] hover:bg-[#4D7FA8]'
                    }`}
                  >
                    {fixApplied ? 'PR #491 Opened' : 'Open PR with Patch'}
                  </button>
                </div>
              )}

              {/* Triage Activity Log */}
              <div className="space-y-2 pt-2 border-t border-[#2A3441]">
                <div className="text-xs font-semibold text-[#E7E9EC] flex items-center gap-1.5">
                  <MessageSquare className="w-3.5 h-3.5 text-[#3F6B8F]" />
                  Triage Notes & Discussion
                </div>

                <div className="space-y-2">
                  {notes.map((note, i) => (
                    <div key={i} className="p-2.5 rounded bg-[#1B222C] border border-[#2A3441]/80 space-y-1">
                      <div className="flex items-center justify-between text-[10px] text-[#9CA6B2]">
                        <span className="font-semibold text-[#E7E9EC]">{note.author}</span>
                        <span>{note.time}</span>
                      </div>
                      <p className="text-xs text-[#9CA6B2] font-sans">{note.text}</p>
                    </div>
                  ))}
                </div>

                <form onSubmit={handleAddNote} className="flex gap-2 pt-1">
                  <input
                    type="text"
                    value={triageNote}
                    onChange={(e) => setTriageNote(e.target.value)}
                    placeholder="Add triage note or mitigation reason..."
                    className="flex-1 px-3 py-1.5 rounded bg-[#0E1116] border border-[#2A3441] text-xs text-[#E7E9EC] focus:outline-none focus:border-[#3F6B8F]"
                  />
                  <button
                    type="submit"
                    className="px-3 py-1.5 rounded bg-[#1B222C] border border-[#2A3441] text-[#E7E9EC] hover:border-[#3F6B8F] hover:bg-[#3F6B8F]/20 transition-colors"
                  >
                    <Send className="w-3.5 h-3.5" />
                  </button>
                </form>
              </div>
            </div>
          )}

          {activeTab === 'details' && (
            <div className="space-y-4">
              {/* Metrics Grid */}
              <div className="grid grid-cols-2 gap-3">
                <div className="p-3 rounded-md bg-[#1B222C] border border-[#2A3441]">
                  <div className="text-[10px] text-[#9CA6B2] uppercase">Risk Impact Score</div>
                  <div className="text-xl font-bold text-[#E07A7A] mt-1">
                    {finding.impactScore} <span className="text-xs text-[#9CA6B2]">/ 100</span>
                  </div>
                </div>

                <div className="p-3 rounded-md bg-[#1B222C] border border-[#2A3441]">
                  <div className="text-[10px] text-[#9CA6B2] uppercase">Estimated Debt Cost</div>
                  <div className="text-xl font-bold text-[#8FB7D9] mt-1">
                    {finding.debtHours} <span className="text-xs text-[#9CA6B2]">hours</span>
                  </div>
                </div>

                <div className="p-3 rounded-md bg-[#1B222C] border border-[#2A3441]">
                  <div className="text-[10px] text-[#9CA6B2] uppercase">Blast Radius</div>
                  <div className="text-sm font-bold text-[#E7E9EC] mt-1 capitalize">
                    {finding.blastRadius.replace('_', ' ')}
                  </div>
                </div>

                <div className="p-3 rounded-md bg-[#1B222C] border border-[#2A3441]">
                  <div className="text-[10px] text-[#9CA6B2] uppercase">Repository / Branch</div>
                  <div className="text-xs font-bold text-[#E7E9EC] mt-1 truncate">
                    {finding.repository}:{finding.branch}
                  </div>
                </div>
              </div>

              {/* Attribution */}
              <div className="p-3 rounded-md bg-[#1B222C] border border-[#2A3441] space-y-2">
                <div className="text-xs font-semibold text-[#E7E9EC]">Git Attribution & History</div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <span className="text-[#9CA6B2]">Introduced by: </span>
                    <span className="text-[#E7E9EC] font-semibold">{finding.author}</span>
                  </div>
                  <div>
                    <span className="text-[#9CA6B2]">Commit: </span>
                    <span className="text-[#3F6B8F] font-semibold">{finding.commitHash}</span>
                  </div>
                  <div className="col-span-2">
                    <span className="text-[#9CA6B2]">Detected Date: </span>
                    <span className="text-[#E7E9EC]">{new Date(finding.introducedDate).toLocaleString()}</span>
                  </div>
                </div>
              </div>

              {/* Assignee */}
              {finding.assignee && (
                <div className="p-3 rounded-md bg-[#1B222C] border border-[#2A3441] flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <img
                      src={finding.assignee.avatar}
                      alt={finding.assignee.name}
                      className="w-8 h-8 rounded-full border border-[#2A3441]"
                    />
                    <div>
                      <div className="text-xs font-semibold text-[#E7E9EC]">{finding.assignee.name}</div>
                      <div className="text-[10px] text-[#9CA6B2]">{finding.assignee.email}</div>
                    </div>
                  </div>
                  <button className="text-xs text-[#3F6B8F] hover:underline">Reassign</button>
                </div>
              )}
            </div>
          )}

          {activeTab === 'sarif' && (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-[11px] text-[#9CA6B2]">
                <span>Static Analysis Results Interchange Format (SARIF v2.1)</span>
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(sarifPayload);
                    alert('SARIF JSON copied to clipboard');
                  }}
                  className="text-[#3F6B8F] hover:underline"
                >
                  Copy JSON
                </button>
              </div>
              <pre className="p-3 rounded-md bg-[#0E1116] border border-[#2A3441] text-[11px] text-[#9CA6B2] overflow-x-auto">
                {sarifPayload}
              </pre>
            </div>
          )}
        </div>
      </div>
    </>
  );
};
