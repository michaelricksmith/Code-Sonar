import React from 'react';
import {
  LayoutDashboard,
  ShieldAlert,
  Flame,
  History,
  GitCompare,
  Settings,
  Terminal,
  Activity,
  Radio,
  Sparkles,
  ChevronRight,
  Cpu,
} from 'lucide-react';

export type NavPage = 'overview' | 'findings' | 'hotspots' | 'history' | 'drift' | 'settings';

interface SidebarProps {
  activePage: NavPage;
  onSelectPage: (page: NavPage) => void;
  findingsCount: number;
  criticalCount: number;
  driftCount: number;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activePage,
  onSelectPage,
  findingsCount,
  criticalCount,
  driftCount,
}) => {
  const navItems: {
    id: NavPage;
    label: string;
    icon: React.ElementType;
    badge?: string | number;
    badgeVariant?: 'critical' | 'default' | 'steel';
  }[] = [
    {
      id: 'overview',
      label: 'Command Overview',
      icon: LayoutDashboard,
    },
    {
      id: 'findings',
      label: 'AST Findings',
      icon: ShieldAlert,
      badge: criticalCount > 0 ? `${criticalCount} crit` : findingsCount,
      badgeVariant: criticalCount > 0 ? 'critical' : 'default',
    },
    {
      id: 'hotspots',
      label: 'Risk Hotspots',
      icon: Flame,
      badge: '6 files',
      badgeVariant: 'steel',
    },
    {
      id: 'drift',
      label: 'Arch Drift & Bypass',
      icon: GitCompare,
      badge: driftCount,
      badgeVariant: driftCount > 0 ? 'critical' : 'default',
    },
    {
      id: 'history',
      label: 'Audit & Gating Log',
      icon: History,
    },
    {
      id: 'settings',
      label: 'Policy Gates & Rules',
      icon: Settings,
    },
  ];

  return (
    <aside className="w-64 bg-[#11161F] border-r border-[#222B38] flex flex-col justify-between select-none shrink-0 h-full font-mono">
      {/* Brand & Organization */}
      <div>
        <div className="h-14 flex items-center px-4 border-b border-[#222B38] gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-[#0B0E14] border border-[#3F6B8F]/50 flex items-center justify-center text-[#8FB7D9] shadow-[0_0_10px_rgba(63,107,143,0.3)]">
            <Radio className="w-4 h-4 text-[#3F6B8F] animate-pulse" />
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <span className="font-bold text-sm text-[#E7E9EC] tracking-tight">CODE SONAR</span>
              <span className="text-[9px] px-1 py-0.2 rounded bg-[#3F6B8F]/20 text-[#8FB7D9] border border-[#3F6B8F]/40">
                PRO
              </span>
            </div>
            <p className="text-[10px] text-[#9CA6B2]">Risk Intelligence Engine</p>
          </div>
        </div>

        {/* Navigation items */}
        <nav className="p-3 space-y-1">
          <div className="px-2 py-1 text-[10px] text-[#6C7989] uppercase tracking-wider">
            Risk & Vector Analytics
          </div>

          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = activePage === item.id;

            return (
              <button
                key={item.id}
                onClick={() => onSelectPage(item.id)}
                className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs transition-all ${
                  isActive
                    ? 'bg-[#1B222C] text-[#E7E9EC] font-semibold border border-[#3F6B8F]/60 shadow-[0_0_15px_rgba(63,107,143,0.15)]'
                    : 'text-[#9CA6B2] hover:bg-[#151A21] hover:text-[#E7E9EC] border border-transparent'
                }`}
              >
                <div className="flex items-center gap-2.5">
                  <Icon
                    className={`w-4 h-4 transition-colors ${
                      isActive ? 'text-[#3F6B8F]' : 'text-[#6C7989]'
                    }`}
                  />
                  <span>{item.label}</span>
                </div>

                {item.badge !== undefined && (
                  <span
                    className={`text-[10px] px-1.5 py-0.5 rounded ${
                      item.badgeVariant === 'critical'
                        ? 'bg-[#8F3D3D]/30 text-[#E07A7A] border border-[#8F3D3D]/50 shadow-[0_0_8px_rgba(224,122,122,0.2)]'
                        : item.badgeVariant === 'steel'
                        ? 'bg-[#3F6B8F]/20 text-[#8FB7D9] border border-[#3F6B8F]/40'
                        : 'bg-[#0B0E14] text-[#9CA6B2] border border-[#222B38]'
                    }`}
                  >
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Bottom info & Sonar CLI hook */}
      <div className="p-3 border-t border-[#222B38] space-y-3 bg-[#0B0E14]/70">
        {/* CLI status */}
        <div className="p-2.5 rounded-lg bg-[#0B0E14] border border-[#222B38] text-[11px]">
          <div className="flex items-center justify-between text-[#9CA6B2] mb-1">
            <span className="flex items-center gap-1">
              <Terminal className="w-3 h-3 text-[#3F6B8F]" />
              <span>CI Hook Status</span>
            </span>
            <span className="text-[#4F8A73] font-bold">Active</span>
          </div>
          <code className="text-[10px] text-[#6C7989] block truncate hover:text-[#E7E9EC] transition-colors cursor-pointer select-all">
            $ sonar scan --diff HEAD
          </code>
        </div>

        {/* Engine metadata */}
        <div className="flex items-center justify-between text-[10px] text-[#6C7989] px-1">
          <span className="flex items-center gap-1 text-[#4F8A73]">
            <Cpu className="w-3 h-3 text-[#4F8A73]" />
            AST v2.4 (V8 online)
          </span>
          <span>42ms</span>
        </div>
      </div>
    </aside>
  );
};
