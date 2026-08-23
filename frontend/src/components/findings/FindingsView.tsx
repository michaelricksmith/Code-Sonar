import React, { useState } from 'react';
import {
  Search,
  Filter,
  ArrowUpDown,
  Download,
  CheckSquare,
  Square,
  ShieldAlert,
  AlertTriangle,
  Layers,
  ChevronRight,
  ExternalLink,
  RefreshCw,
  SlidersHorizontal,
  CheckCircle2,
  FileCode,
  Sparkles,
} from 'lucide-react';
import { Finding, Severity, Category, FindingStatus } from '../../types';
import { SeverityBadge, CategoryBadge } from '../common/RiskBadge';

interface FindingsViewProps {
  findings: Finding[];
  onSelectFinding: (finding: Finding) => void;
  onUpdateStatus: (id: string, status: FindingStatus) => void;
  onBatchUpdateStatus: (ids: string[], status: FindingStatus) => void;
}

export const FindingsView: React.FC<FindingsViewProps> = ({
  findings,
  onSelectFinding,
  onUpdateStatus,
  onBatchUpdateStatus,
}) => {
  const [search, setSearch] = useState('');
  const [selectedSeverity, setSelectedSeverity] = useState<Severity | 'all'>('all');
  const [selectedCategory, setSelectedCategory] = useState<Category | 'all'>('all');
  const [selectedStatus, setSelectedStatus] = useState<FindingStatus | 'all'>('all');
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [sortBy, setSortBy] = useState<'impact' | 'debt' | 'recent' | 'severity'>('impact');

  // Filter findings
  const filteredFindings = findings.filter((f) => {
    if (selectedSeverity !== 'all' && f.severity !== selectedSeverity) return false;
    if (selectedCategory !== 'all' && f.category !== selectedCategory) return false;
    if (selectedStatus !== 'all' && f.status !== selectedStatus) return false;

    if (search.trim()) {
      const q = search.toLowerCase();
      const match =
        f.title.toLowerCase().includes(q) ||
        f.ruleId.toLowerCase().includes(q) ||
        f.filePath.toLowerCase().includes(q) ||
        f.author.toLowerCase().includes(q) ||
        (f.cwe && f.cwe.toLowerCase().includes(q)) ||
        (f.cve && f.cve.toLowerCase().includes(q));
      if (!match) return false;
    }
    return true;
  });

  // Sort findings
  const sortedFindings = [...filteredFindings].sort((a, b) => {
    if (sortBy === 'impact') return b.impactScore - a.impactScore;
    if (sortBy === 'debt') return b.debtHours - a.debtHours;
    if (sortBy === 'recent') return new Date(b.introducedDate).getTime() - new Date(a.introducedDate).getTime();
    if (sortBy === 'severity') {
      const rank: Record<Severity, number> = { critical: 4, high: 3, warning: 2, healthy: 1, info: 0 };
      return rank[b.severity] - rank[a.severity];
    }
    return 0;
  });

  const toggleSelectAll = () => {
    if (selectedIds.length === sortedFindings.length) {
      setSelectedIds([]);
    } else {
      setSelectedIds(sortedFindings.map((f) => f.id));
    }
  };

  const toggleSelectOne = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (selectedIds.includes(id)) {
      setSelectedIds(selectedIds.filter((x) => x !== id));
    } else {
      setSelectedIds([...selectedIds, id]);
    }
  };

  const handleBatchTriage = (status: FindingStatus) => {
    if (selectedIds.length === 0) return;
    onBatchUpdateStatus(selectedIds, status);
    setSelectedIds([]);
  };

  const exportSarif = () => {
    const subset = findings.filter((f) => selectedIds.length === 0 || selectedIds.includes(f.id));
    const payload = JSON.stringify(
      {
        version: '2.1.0',
        runs: [
          {
            tool: { driver: { name: 'CodeSonar', version: '2.4.0' } },
            results: subset.map((f) => ({
              ruleId: f.ruleId,
              level: f.severity === 'critical' ? 'error' : 'warning',
              message: { text: f.description },
              locations: [
                {
                  physicalLocation: {
                    artifactLocation: { uri: f.filePath },
                    region: { startLine: f.lineRange[0], endLine: f.lineRange[1] },
                  },
                },
              ],
            })),
          },
        ],
      },
      null,
      2
    );

    const blob = new Blob([payload], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `codesonar-findings-${Date.now()}.sarif`;
    a.click();
  };

  return (
    <div className="space-y-4 pb-12">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-3 border-b border-[#2A3441]">
        <div>
          <h1 className="text-xl font-bold font-mono tracking-tight text-[#E7E9EC]">
            Software Risk Findings Explorer
          </h1>
          <p className="text-xs text-[#9CA6B2] font-mono mt-0.5">
            Static analysis violations, security vulnerabilities, and architectural layer breaches.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={exportSarif}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-[#151A21] border border-[#2A3441] text-xs font-mono text-[#E7E9EC] hover:border-[#3F6B8F] hover:bg-[#1B222C] transition-colors"
          >
            <Download className="w-3.5 h-3.5 text-[#3F6B8F]" />
            <span>Export SARIF ({selectedIds.length > 0 ? selectedIds.length : sortedFindings.length})</span>
          </button>
        </div>
      </div>

      {/* Filter & Search Bar */}
      <div className="p-3 rounded-lg bg-[#151A21] border border-[#2A3441] space-y-3 font-mono text-xs">
        <div className="flex flex-col sm:flex-row gap-3">
          {/* Search Input */}
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-[#9CA6B2] absolute left-3 top-2.5" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter by rule, title, file path, CWE, author, or commit..."
              className="w-full pl-9 pr-3 py-1.5 rounded-md bg-[#0E1116] border border-[#2A3441] text-xs text-[#E7E9EC] placeholder:text-[#6C7989] focus:outline-none focus:border-[#3F6B8F]"
            />
          </div>

          {/* Sort By */}
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-[#9CA6B2]">Sort:</span>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as any)}
              className="bg-[#0E1116] border border-[#2A3441] text-[#E7E9EC] rounded px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:border-[#3F6B8F]"
            >
              <option value="impact">Risk Impact (Highest first)</option>
              <option value="severity">Severity (Critical first)</option>
              <option value="debt">Debt Hours (Largest first)</option>
              <option value="recent">Most Recently Introduced</option>
            </select>
          </div>
        </div>

        {/* Filter Pills */}
        <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-[#2A3441]/60">
          <span className="text-[#6C7989] text-[11px] uppercase tracking-wider flex items-center gap-1">
            <Filter className="w-3 h-3" /> Filters:
          </span>

          {/* Severity selector */}
          <div className="flex items-center gap-1">
            {(['all', 'critical', 'high', 'warning'] as const).map((sev) => (
              <button
                key={sev}
                onClick={() => setSelectedSeverity(sev)}
                className={`px-2 py-0.5 rounded text-[11px] uppercase transition-colors ${
                  selectedSeverity === sev
                    ? 'bg-[#3F6B8F] text-[#E7E9EC] font-bold'
                    : 'bg-[#0E1116] text-[#9CA6B2] border border-[#2A3441] hover:text-[#E7E9EC]'
                }`}
              >
                {sev}
              </button>
            ))}
          </div>

          <span className="text-[#2A3441]">|</span>

          {/* Category selector */}
          <div className="flex items-center gap-1 flex-wrap">
            {(['all', 'security', 'architecture', 'reliability', 'tech_debt', 'compliance'] as const).map((cat) => (
              <button
                key={cat}
                onClick={() => setSelectedCategory(cat)}
                className={`px-2 py-0.5 rounded text-[11px] capitalize transition-colors ${
                  selectedCategory === cat
                    ? 'bg-[#1B222C] text-[#8FB7D9] font-bold border border-[#3F6B8F]'
                    : 'bg-[#0E1116] text-[#9CA6B2] border border-[#2A3441] hover:text-[#E7E9EC]'
                }`}
              >
                {cat.replace('_', ' ')}
              </button>
            ))}
          </div>

          <span className="text-[#2A3441]">|</span>

          {/* Status selector */}
          <div className="flex items-center gap-1">
            {(['all', 'open', 'in_triage', 'suppressed', 'resolved'] as const).map((stat) => (
              <button
                key={stat}
                onClick={() => setSelectedStatus(stat)}
                className={`px-2 py-0.5 rounded text-[11px] capitalize transition-colors ${
                  selectedStatus === stat
                    ? 'bg-[#1B222C] text-[#E7E9EC] font-bold border border-[#2A3441]'
                    : 'bg-[#0E1116] text-[#9CA6B2] border border-[#2A3441] hover:text-[#E7E9EC]'
                }`}
              >
                {stat.replace('_', ' ')}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Bulk Action Bar (when items selected) */}
      {selectedIds.length > 0 && (
        <div className="p-2.5 rounded-md bg-[#1B222C] border border-[#3F6B8F] flex items-center justify-between font-mono text-xs animate-in fade-in duration-150">
          <div className="flex items-center gap-2 text-[#E7E9EC]">
            <span className="font-bold text-[#8FB7D9]">{selectedIds.length} findings selected</span>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => handleBatchTriage('in_triage')}
              className="px-2.5 py-1 rounded bg-[#151A21] border border-[#2A3441] text-[#E7E9EC] hover:border-[#3F6B8F]"
            >
              Mark In Triage
            </button>
            <button
              onClick={() => handleBatchTriage('suppressed')}
              className="px-2.5 py-1 rounded bg-[#151A21] border border-[#2A3441] text-[#E8B468] hover:border-[#C28A3D]"
            >
              Suppress / Accept Risk
            </button>
            <button
              onClick={() => handleBatchTriage('resolved')}
              className="px-2.5 py-1 rounded bg-[#4F8A73]/20 border border-[#4F8A73]/50 text-[#7CC4A8] hover:bg-[#4F8A73]/30"
            >
              Mark Resolved
            </button>
          </div>
        </div>
      )}

      {/* Findings Table */}
      <div className="rounded-lg bg-[#151A21] border border-[#2A3441] overflow-hidden">
        {/* Table Header */}
        <div className="grid grid-cols-12 gap-3 px-4 py-2.5 bg-[#1B222C]/70 border-b border-[#2A3441] text-[11px] font-mono text-[#9CA6B2] uppercase tracking-wider items-center select-none">
          <div className="col-span-1 flex items-center gap-2">
            <button onClick={toggleSelectAll} className="text-[#9CA6B2] hover:text-[#E7E9EC]">
              {selectedIds.length === sortedFindings.length && sortedFindings.length > 0 ? (
                <CheckSquare className="w-3.5 h-3.5 text-[#3F6B8F]" />
              ) : (
                <Square className="w-3.5 h-3.5" />
              )}
            </button>
            <span>ID</span>
          </div>
          <div className="col-span-5">Finding & Location</div>
          <div className="col-span-2">Severity & Domain</div>
          <div className="col-span-2">Impact / Debt</div>
          <div className="col-span-2 text-right">Status / Actions</div>
        </div>

        {/* Rows */}
        <div className="divide-y divide-[#2A3441]">
          {sortedFindings.length === 0 ? (
            <div className="p-8 text-center text-[#9CA6B2] font-mono text-xs">
              No findings matched the selected filters.
            </div>
          ) : (
            sortedFindings.map((finding) => {
              const isSelected = selectedIds.includes(finding.id);

              return (
                <div
                  key={finding.id}
                  onClick={() => onSelectFinding(finding)}
                  className={`grid grid-cols-12 gap-3 px-4 py-3 items-center hover:bg-[#1B222C] cursor-pointer transition-colors font-mono text-xs ${
                    isSelected ? 'bg-[#1B222C]/50' : ''
                  }`}
                >
                  {/* Select Checkbox & ID */}
                  <div className="col-span-1 flex items-center gap-2">
                    <button
                      onClick={(e) => toggleSelectOne(finding.id, e)}
                      className="text-[#9CA6B2] hover:text-[#E7E9EC]"
                    >
                      {isSelected ? (
                        <CheckSquare className="w-3.5 h-3.5 text-[#3F6B8F]" />
                      ) : (
                        <Square className="w-3.5 h-3.5" />
                      )}
                    </button>
                    <span className="text-[#3F6B8F] font-bold">{finding.id}</span>
                  </div>

                  {/* Title & File Path */}
                  <div className="col-span-5 space-y-1 truncate pr-2">
                    <div className="font-semibold text-[#E7E9EC] truncate flex items-center gap-2">
                      <span className="truncate">{finding.title}</span>
                      {finding.suggestedFix && (
                        <span className="text-[10px] text-[#7CC4A8] bg-[#4F8A73]/10 px-1 py-0.2 rounded border border-[#4F8A73]/30 shrink-0">
                          Auto-Fix Available
                        </span>
                      )}
                    </div>
                    <div className="text-[11px] text-[#6C7989] truncate flex items-center gap-2">
                      <FileCode className="w-3 h-3 text-[#3F6B8F]" />
                      <span className="truncate">{finding.filePath}:{finding.lineRange[0]}</span>
                      <span>•</span>
                      <span>{finding.author}</span>
                      <span>•</span>
                      <span className="text-[#3F6B8F]">{finding.commitHash}</span>
                    </div>
                  </div>

                  {/* Severity & Domain */}
                  <div className="col-span-2 flex flex-col gap-1 items-start">
                    <SeverityBadge severity={finding.severity} size="sm" />
                    <CategoryBadge category={finding.category} />
                  </div>

                  {/* Impact & Debt */}
                  <div className="col-span-2 space-y-0.5">
                    <div className="flex items-center gap-1.5">
                      <span className="text-[#9CA6B2] text-[11px]">Impact:</span>
                      <span className="font-bold text-[#E07A7A]">{finding.impactScore}/100</span>
                    </div>
                    <div className="text-[11px] text-[#8FB7D9]">
                      {finding.debtHours}h debt • <span className="capitalize text-[#6C7989]">{finding.blastRadius.replace('_', ' ')}</span>
                    </div>
                  </div>

                  {/* Status & Drawer Trigger */}
                  <div className="col-span-2 flex items-center justify-end gap-2">
                    <span
                      className={`text-[11px] px-2 py-0.5 rounded capitalize ${
                        finding.status === 'open'
                          ? 'bg-[#8F3D3D]/20 text-[#E07A7A] border border-[#8F3D3D]/30'
                          : finding.status === 'in_triage'
                          ? 'bg-[#C28A3D]/20 text-[#E8B468] border border-[#C28A3D]/30'
                          : finding.status === 'suppressed'
                          ? 'bg-[#1B222C] text-[#9CA6B2] border border-[#2A3441]'
                          : 'bg-[#4F8A73]/20 text-[#7CC4A8] border border-[#4F8A73]/30'
                      }`}
                    >
                      {finding.status.replace('_', ' ')}
                    </span>
                    <ChevronRight className="w-4 h-4 text-[#6C7989]" />
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};
