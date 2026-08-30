import React, { useState } from 'react';
import {
  GitBranch,
  Search,
  RefreshCw,
  GitPullRequest,
  CheckCircle2,
  AlertTriangle,
  FolderGit2,
  ChevronDown,
  ExternalLink,
  Shield,
  Bell,
  Radio,
  Zap,
} from 'lucide-react';
import { RepositoryOption } from '../../types';

interface HeaderProps {
  currentRepo: RepositoryOption;
  repos: RepositoryOption[];
  onSelectRepo: (repo: RepositoryOption) => void;
  onOpenCommandPalette: () => void;
  onTriggerScan: () => void;
  isScanning: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  currentRepo,
  repos,
  onSelectRepo,
  onOpenCommandPalette,
  onTriggerScan,
  isScanning,
}) => {
  const [repoDropdownOpen, setRepoDropdownOpen] = useState(false);
  const [branchDropdownOpen, setBranchDropdownOpen] = useState(false);
  const [selectedBranch, setSelectedBranch] = useState(currentRepo.branch);

  const branches = ['main', 'release/v2026.08.4', 'feat/payment-reconciliation', 'fix/sql-injection-patch'];

  return (
    <header className="h-14 bg-[#11161F] border-b border-[#222B38] flex items-center justify-between px-4 z-30 select-none font-mono">
      {/* Left: Repository & Branch Switcher */}
      <div className="flex items-center gap-3">
        {/* Repo Picker */}
        <div className="relative">
          <button
            onClick={() => setRepoDropdownOpen(!repoDropdownOpen)}
            className="flex items-center gap-2 px-2.5 py-1.5 rounded-md bg-[#0B0E14] border border-[#222B38] text-xs text-[#E7E9EC] hover:border-[#3F6B8F] transition-colors"
          >
            <FolderGit2 className="w-3.5 h-3.5 text-[#3F6B8F]" />
            <span className="font-semibold">{currentRepo.name}</span>
            <ChevronDown className="w-3 h-3 text-[#9CA6B2]" />
          </button>

          {repoDropdownOpen && (
            <>
              <div
                className="fixed inset-0 z-40"
                onClick={() => setRepoDropdownOpen(false)}
              />
              <div className="absolute left-0 mt-1 w-64 rounded-md bg-[#11161F] border border-[#2A3441] shadow-2xl py-1 z-50">
                <div className="px-3 py-1.5 text-[10px] text-[#9CA6B2] uppercase tracking-wider border-b border-[#222B38]">
                  Select Monitored Microservice
                </div>
                {repos.map((repo) => (
                  <button
                    key={repo.id}
                    onClick={() => {
                      onSelectRepo(repo);
                      setRepoDropdownOpen(false);
                    }}
                    className={`w-full flex items-center justify-between px-3 py-2 text-xs hover:bg-[#1B222C] text-left transition-colors ${
                      repo.id === currentRepo.id ? 'bg-[#1B222C] text-[#E7E9EC]' : 'text-[#9CA6B2]'
                    }`}
                  >
                    <div className="flex items-center gap-2 truncate">
                      <span
                        className={`w-1.5 h-1.5 rounded-full ${
                          repo.overallScore >= 80 ? 'bg-[#4F8A73]' : repo.overallScore >= 70 ? 'bg-[#C28A3D]' : 'bg-[#8F3D3D]'
                        }`}
                      />
                      <span className="truncate">{repo.name}</span>
                    </div>
                    <span className="text-[11px] px-1.5 py-0.5 rounded bg-[#0B0E14] border border-[#222B38]">
                      {repo.overallScore}/850
                    </span>
                  </button>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Branch Picker */}
        <div className="relative">
          <button
            onClick={() => setBranchDropdownOpen(!branchDropdownOpen)}
            className="flex items-center gap-1.5 px-2 py-1.5 rounded-md bg-[#0B0E14] border border-[#222B38] text-xs text-[#9CA6B2] hover:text-[#E7E9EC] hover:border-[#3F6B8F] transition-colors"
          >
            <GitBranch className="w-3.5 h-3.5 text-[#9CA6B2]" />
            <span>{selectedBranch}</span>
            <ChevronDown className="w-3 h-3 text-[#9CA6B2]" />
          </button>

          {branchDropdownOpen && (
            <>
              <div
                className="fixed inset-0 z-40"
                onClick={() => setBranchDropdownOpen(false)}
              />
              <div className="absolute left-0 mt-1 w-52 rounded-md bg-[#11161F] border border-[#2A3441] shadow-2xl py-1 z-50">
                <div className="px-3 py-1.5 text-[10px] text-[#9CA6B2] uppercase tracking-wider border-b border-[#222B38]">
                  Target Branch
                </div>
                {branches.map((branch) => (
                  <button
                    key={branch}
                    onClick={() => {
                      setSelectedBranch(branch);
                      setBranchDropdownOpen(false);
                    }}
                    className={`w-full flex items-center justify-between px-3 py-1.5 text-xs hover:bg-[#1B222C] text-left transition-colors ${
                      branch === selectedBranch ? 'bg-[#1B222C] text-[#E7E9EC]' : 'text-[#9CA6B2]'
                    }`}
                  >
                    <span>{branch}</span>
                    {branch === 'main' && (
                      <span className="text-[10px] text-[#4F8A73]">default</span>
                    )}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Quality Gate Status indicator */}
        <div className="hidden lg:flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-[#8F3D3D]/20 border border-[#8F3D3D]/40 text-xs text-[#E07A7A]">
          <span className="w-2 h-2 rounded-full bg-[#8F3D3D] animate-pulse" />
          <span>CI Gate: Blocked (2 CVEs)</span>
        </div>
      </div>

      {/* Center: Command Palette Trigger */}
      <div className="flex-1 max-w-md mx-4">
        <button
          onClick={onOpenCommandPalette}
          className="w-full flex items-center justify-between px-3 py-1.5 rounded-md bg-[#0B0E14] border border-[#222B38] text-xs text-[#9CA6B2] hover:border-[#3F6B8F] hover:text-[#E7E9EC] transition-colors group"
        >
          <div className="flex items-center gap-2">
            <Search className="w-3.5 h-3.5 text-[#9CA6B2] group-hover:text-[#E7E9EC]" />
            <span className="text-[11px]">Search AST findings, rules, files, CVEs...</span>
          </div>
          <kbd className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-[#1B222C] border border-[#222B38] text-[10px] text-[#9CA6B2]">
            ⌘K
          </kbd>
        </button>
      </div>

      {/* Right: Actions, Live Scan Pulse & Profile */}
      <div className="flex items-center gap-3">
        {/* Scan Status & Trigger */}
        <div className="flex items-center gap-2">
          <button
            onClick={onTriggerScan}
            disabled={isScanning}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-[#3F6B8F] text-[#E7E9EC] font-semibold text-xs hover:bg-[#4D7FA8] active:scale-95 disabled:opacity-50 transition-all shadow-[0_0_12px_rgba(63,107,143,0.3)]"
            title="Trigger deep AST static analysis scan"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isScanning ? 'animate-spin' : ''}`} />
            <span>{isScanning ? 'Scanning AST...' : 'Deep Sonar Scan'}</span>
          </button>
        </div>

        <div className="h-4 w-px bg-[#222B38]" />

        {/* Notifications & Live feed */}
        <button
          onClick={onOpenCommandPalette}
          className="relative p-1.5 rounded-md text-[#9CA6B2] hover:text-[#E7E9EC] hover:bg-[#1B222C] transition-colors"
          title="Recent alerts"
        >
          <Bell className="w-4 h-4" />
          <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-[#8F3D3D] ring-2 ring-[#11161F]" />
        </button>

        {/* User avatar */}
        <div className="flex items-center gap-2 pl-1">
          <div className="w-7 h-7 rounded-full bg-[#1B222C] border border-[#2A3441] flex items-center justify-center text-xs font-semibold text-[#8FB7D9]">
            MR
          </div>
        </div>
      </div>
    </header>
  );
};
