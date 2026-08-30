import React, { useState, useEffect, useRef } from 'react';
import { Search, ShieldAlert, Flame, GitCompare, History, Settings, Play, ArrowRight, X, FileCode } from 'lucide-react';
import { Finding, RiskHotspot } from '../../types';
import { NavPage } from './Sidebar';

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  findings: Finding[];
  hotspots: RiskHotspot[];
  onSelectFinding: (finding: Finding) => void;
  onNavigate: (page: NavPage) => void;
  onTriggerScan: () => void;
}

export const CommandPalette: React.FC<CommandPaletteProps> = ({
  isOpen,
  onClose,
  findings,
  hotspots,
  onSelectFinding,
  onNavigate,
  onTriggerScan,
}) => {
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 50);
      setQuery('');
      setSelectedIndex(0);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  // Filter items
  const filteredFindings = findings.filter(
    (f) =>
      f.title.toLowerCase().includes(query.toLowerCase()) ||
      f.ruleId.toLowerCase().includes(query.toLowerCase()) ||
      f.filePath.toLowerCase().includes(query.toLowerCase()) ||
      (f.cwe && f.cwe.toLowerCase().includes(query.toLowerCase()))
  );

  const filteredHotspots = hotspots.filter((h) =>
    h.filePath.toLowerCase().includes(query.toLowerCase())
  );

  const quickActions = [
    {
      id: 'act-scan',
      label: 'Run Static Analysis Scan (Full AST)',
      icon: Play,
      action: () => {
        onTriggerScan();
        onClose();
      },
    },
    {
      id: 'act-findings',
      label: 'Go to Critical Findings Explorer',
      icon: ShieldAlert,
      action: () => {
        onNavigate('findings');
        onClose();
      },
    },
    {
      id: 'act-hotspots',
      label: 'Inspect High Churn Risk Hotspots',
      icon: Flame,
      action: () => {
        onNavigate('hotspots');
        onClose();
      },
    },
    {
      id: 'act-drift',
      label: 'View Architectural Layer Drift',
      icon: GitCompare,
      action: () => {
        onNavigate('drift');
        onClose();
      },
    },
    {
      id: 'act-settings',
      label: 'Edit CI/CD Quality Gate Policies',
      icon: Settings,
      action: () => {
        onNavigate('settings');
        onClose();
      },
    },
  ].filter((a) => a.label.toLowerCase().includes(query.toLowerCase()));

  return (
    <>
      <div className="fixed inset-0 bg-black/70 z-50 backdrop-blur-[2px]" onClick={onClose} />
      <div className="fixed top-24 left-1/2 -translate-x-1/2 w-full max-w-xl bg-[#151A21] border border-[#2A3441] rounded-lg shadow-2xl z-50 overflow-hidden font-mono text-xs">
        {/* Search Bar */}
        <div className="p-3 border-b border-[#2A3441] flex items-center gap-2.5 bg-[#1B222C]/70">
          <Search className="w-4 h-4 text-[#3F6B8F]" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            placeholder="Type a command, search findings, CVEs, or files..."
            className="flex-1 bg-transparent text-sm text-[#E7E9EC] placeholder:text-[#6C7989] focus:outline-none"
          />
          <kbd className="px-1.5 py-0.5 rounded bg-[#0E1116] border border-[#2A3441] text-[10px] text-[#9CA6B2]">
            ESC
          </kbd>
        </div>

        {/* Results */}
        <div className="max-h-96 overflow-y-auto p-2 space-y-3">
          {/* Quick actions */}
          {quickActions.length > 0 && (
            <div>
              <div className="px-2 py-1 text-[10px] text-[#6C7989] uppercase tracking-wider">
                Quick Actions
              </div>
              {quickActions.map((act) => {
                const Icon = act.icon;
                return (
                  <button
                    key={act.id}
                    onClick={act.action}
                    className="w-full flex items-center justify-between px-2.5 py-2 rounded-md hover:bg-[#1B222C] text-[#E7E9EC] text-left transition-colors group"
                  >
                    <div className="flex items-center gap-2">
                      <Icon className="w-3.5 h-3.5 text-[#3F6B8F]" />
                      <span>{act.label}</span>
                    </div>
                    <ArrowRight className="w-3.5 h-3.5 text-[#6C7989] opacity-0 group-hover:opacity-100 transition-opacity" />
                  </button>
                );
              })}
            </div>
          )}

          {/* Findings */}
          {filteredFindings.length > 0 && (
            <div>
              <div className="px-2 py-1 text-[10px] text-[#6C7989] uppercase tracking-wider">
                Matching Findings
              </div>
              {filteredFindings.slice(0, 5).map((f) => (
                <button
                  key={f.id}
                  onClick={() => {
                    onSelectFinding(f);
                    onClose();
                  }}
                  className="w-full flex items-center justify-between px-2.5 py-2 rounded-md hover:bg-[#1B222C] text-left transition-colors"
                >
                  <div className="truncate pr-2">
                    <div className="flex items-center gap-1.5 truncate">
                      <span className="text-[#3F6B8F] font-bold">{f.id}</span>
                      <span className="text-[#E7E9EC] truncate">{f.title}</span>
                    </div>
                    <div className="text-[10px] text-[#6C7989] truncate">{f.filePath}</div>
                  </div>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded uppercase font-semibold shrink-0 ${
                    f.severity === 'critical' ? 'bg-[#8F3D3D]/20 text-[#E07A7A]' : 'bg-[#B85C4A]/20 text-[#E58D7C]'
                  }`}>
                    {f.severity}
                  </span>
                </button>
              ))}
            </div>
          )}

          {/* Hotspots */}
          {filteredHotspots.length > 0 && (
            <div>
              <div className="px-2 py-1 text-[10px] text-[#6C7989] uppercase tracking-wider">
                High Risk Files & Hotspots
              </div>
              {filteredHotspots.slice(0, 3).map((h) => (
                <button
                  key={h.id}
                  onClick={() => {
                    onNavigate('hotspots');
                    onClose();
                  }}
                  className="w-full flex items-center justify-between px-2.5 py-2 rounded-md hover:bg-[#1B222C] text-left transition-colors"
                >
                  <div className="flex items-center gap-2 truncate">
                    <FileCode className="w-3.5 h-3.5 text-[#B85C4A]" />
                    <span className="text-[#E7E9EC] truncate">{h.filePath}</span>
                  </div>
                  <span className="text-[10px] text-[#B85C4A] font-bold">
                    Risk {h.riskScore}
                  </span>
                </button>
              ))}
            </div>
          )}

          {quickActions.length === 0 && filteredFindings.length === 0 && filteredHotspots.length === 0 && (
            <div className="p-6 text-center text-[#9CA6B2] text-xs">
              No matching records or commands for "{query}"
            </div>
          )}
        </div>
      </div>
    </>
  );
};
