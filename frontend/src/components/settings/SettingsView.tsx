import React, { useState } from 'react';
import {
  Settings,
  Shield,
  Sliders,
  Bell,
  Key,
  Users,
  GitBranch,
  Check,
  Copy,
  Plus,
  Trash2,
  Lock,
  Sparkles,
} from 'lucide-react';
import { QualityGatePolicy } from '../../types';

interface SettingsViewProps {
  policies: QualityGatePolicy[];
}

export const SettingsView: React.FC<SettingsViewProps> = ({ policies: initialPolicies }) => {
  const [activeTab, setActiveTab] = useState<'gates' | 'weights' | 'integrations' | 'api' | 'team'>('gates');
  const [policies, setPolicies] = useState<QualityGatePolicy[]>(initialPolicies);
  const [weights, setWeights] = useState({
    security: 40,
    architecture: 25,
    reliability: 20,
    techDebt: 10,
    compliance: 5,
  });
  const [copiedKey, setCopiedKey] = useState(false);
  const [minScoreThreshold, setMinScoreThreshold] = useState(75);

  const togglePolicy = (id: string) => {
    setPolicies(
      policies.map((p) => (p.id === id ? { ...p, enabled: !p.enabled } : p))
    );
  };

  const handleCopyCliToken = () => {
    navigator.clipboard.writeText('sonar_live_sec_993f48a17bc940e8a88192c7');
    setCopiedKey(true);
    setTimeout(() => setCopiedKey(false), 2000);
  };

  return (
    <div className="space-y-6 pb-12">
      {/* Header */}
      <div className="pb-3 border-b border-[#2A3441]">
        <h1 className="text-xl font-bold font-mono tracking-tight text-[#E7E9EC]">
          Platform & Quality Gate Settings
        </h1>
        <p className="text-xs text-[#9CA6B2] font-mono mt-0.5">
          Configure risk thresholds, CI gating policies, scoring formula weights, and repository webhooks.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-[#2A3441] bg-[#151A21] rounded-t-lg px-2">
        {[
          { id: 'gates', label: 'CI/CD Quality Gates', icon: Shield },
          { id: 'weights', label: 'Risk Scoring Weights', icon: Sliders },
          { id: 'integrations', label: 'Integrations & VCS', icon: GitBranch },
          { id: 'api', label: 'CLI Tokens & API', icon: Key },
          { id: 'team', label: 'Team & RBAC', icon: Users },
        ].map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;

          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`flex items-center gap-2 px-3.5 py-2.5 text-xs font-mono border-b-2 font-semibold transition-colors ${
                isActive
                  ? 'border-[#3F6B8F] text-[#E7E9EC] bg-[#1B222C]'
                  : 'border-transparent text-[#9CA6B2] hover:text-[#E7E9EC]'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* Tab Panels */}
      <div className="p-4 rounded-b-lg bg-[#151A21] border border-t-0 border-[#2A3441] font-mono text-xs space-y-6">
        {/* TAB 1: Quality Gate Policies */}
        {activeTab === 'gates' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-[#E7E9EC]">
                  Automated Merge Gating Rules
                </h3>
                <p className="text-xs text-[#9CA6B2]">
                  Pull requests violating active rules will be rejected by the Code Sonar GitHub check.
                </p>
              </div>
              <button
                onClick={() => alert('New policy wizard opened')}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-[#3F6B8F] text-[#E7E9EC] font-semibold hover:bg-[#4D7FA8] transition-colors text-xs font-mono"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>Add Gate Rule</span>
              </button>
            </div>

            <div className="divide-y divide-[#2A3441] border border-[#2A3441] rounded-md bg-[#0E1116] overflow-hidden">
              {policies.length === 0 ? (
                <div className="p-8 text-center text-[#9CA6B2] font-mono text-xs">
                  No quality-gate policies have been synced from the backend yet.
                </div>
              ) : (
                policies.map((policy) => (
                <div
                  key={policy.id}
                  className="p-3.5 flex items-center justify-between hover:bg-[#1B222C]/40 transition-colors"
                >
                  <div className="space-y-1 pr-4">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-[#E7E9EC]">{policy.name}</span>
                      {policy.blockProduction && (
                        <span className="text-[10px] px-1.5 py-0.2 rounded bg-[#8F3D3D]/20 text-[#E07A7A] border border-[#8F3D3D]/40">
                          BLOCKS PROD
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-[#9CA6B2] font-sans">
                      {policy.description}
                    </p>
                  </div>

                  <div className="flex items-center gap-3 shrink-0">
                    <label className="relative inline-flex items-center cursor-pointer">
                      <input
                        type="checkbox"
                        checked={policy.enabled}
                        onChange={() => togglePolicy(policy.id)}
                        className="sr-only peer"
                      />
                      <div className="w-9 h-5 bg-[#1B222C] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-[#9CA6B2] after:border-[#2A3441] after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-[#3F6B8F] peer-checked:after:bg-[#E7E9EC]" />
                    </label>
                  </div>
                </div>
              ))
              )}
            </div>
          </div>
        )}

        {/* TAB 2: Scoring Weights */}
        {activeTab === 'weights' && (
          <div className="space-y-4 max-w-2xl">
            <div>
              <h3 className="text-sm font-semibold text-[#E7E9EC]">
                Risk Formula Weighting
              </h3>
              <p className="text-xs text-[#9CA6B2]">
                Configure how heavily each dimension influences the composite 0-100 Software Risk Score.
              </p>
            </div>

            <div className="space-y-3 bg-[#0E1116] p-4 rounded-md border border-[#2A3441]">
              <div className="space-y-1.5">
                <div className="flex justify-between">
                  <span className="text-[#E7E9EC]">Security Vulnerabilities</span>
                  <span className="text-[#E07A7A] font-bold">{weights.security}%</span>
                </div>
                <input
                  type="range"
                  min={10}
                  max={60}
                  value={weights.security}
                  onChange={(e) => setWeights({ ...weights, security: Number(e.target.value) })}
                  className="w-full accent-[#3F6B8F]"
                />
              </div>

              <div className="space-y-1.5">
                <div className="flex justify-between">
                  <span className="text-[#E7E9EC]">Architectural Drift & Coupling</span>
                  <span className="text-[#E58D7C] font-bold">{weights.architecture}%</span>
                </div>
                <input
                  type="range"
                  min={10}
                  max={50}
                  value={weights.architecture}
                  onChange={(e) => setWeights({ ...weights, architecture: Number(e.target.value) })}
                  className="w-full accent-[#3F6B8F]"
                />
              </div>

              <div className="space-y-1.5">
                <div className="flex justify-between">
                  <span className="text-[#E7E9EC]">Reliability & Unhandled Exceptions</span>
                  <span className="text-[#E8B468] font-bold">{weights.reliability}%</span>
                </div>
                <input
                  type="range"
                  min={5}
                  max={40}
                  value={weights.reliability}
                  onChange={(e) => setWeights({ ...weights, reliability: Number(e.target.value) })}
                  className="w-full accent-[#3F6B8F]"
                />
              </div>

              <div className="space-y-1.5">
                <div className="flex justify-between">
                  <span className="text-[#E7E9EC]">Technical Debt & Complexity (v(G))</span>
                  <span className="text-[#8FB7D9] font-bold">{weights.techDebt}%</span>
                </div>
                <input
                  type="range"
                  min={5}
                  max={30}
                  value={weights.techDebt}
                  onChange={(e) => setWeights({ ...weights, techDebt: Number(e.target.value) })}
                  className="w-full accent-[#3F6B8F]"
                />
              </div>
            </div>

            <div className="flex justify-end">
              <button
                onClick={() => alert('Formula weights updated and risk score recalculated')}
                className="px-4 py-2 rounded bg-[#3F6B8F] text-[#E7E9EC] font-semibold hover:bg-[#4D7FA8] transition-colors"
              >
                Save & Recalculate AST Score
              </button>
            </div>
          </div>
        )}

        {/* TAB 3: Integrations */}
        {activeTab === 'integrations' && (
          <div className="space-y-4">
            <div>
              <h3 className="text-sm font-semibold text-[#E7E9EC]">
                Connected Version Control & Observability
              </h3>
              <p className="text-xs text-[#9CA6B2]">
                Synchronize repos, webhooks, and incident tracking channels.
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="p-3.5 rounded-md bg-[#0E1116] border border-[#2A3441] flex items-center justify-between">
                <div className="space-y-0.5">
                  <div className="font-semibold text-[#E7E9EC]">GitHub Enterprise</div>
                  <div className="text-[11px] text-[#4F8A73]">Connected • 4 repos syncing</div>
                </div>
                <button className="px-2.5 py-1 rounded bg-[#1B222C] border border-[#2A3441] text-[#9CA6B2] hover:text-[#E7E9EC]">
                  Manage
                </button>
              </div>

              <div className="p-3.5 rounded-md bg-[#0E1116] border border-[#2A3441] flex items-center justify-between">
                <div className="space-y-0.5">
                  <div className="font-semibold text-[#E7E9EC]">Slack Alert Webhook</div>
                  <div className="text-[11px] text-[#4F8A73]">Active (#engineering-risk)</div>
                </div>
                <button className="px-2.5 py-1 rounded bg-[#1B222C] border border-[#2A3441] text-[#9CA6B2] hover:text-[#E7E9EC]">
                  Test Hook
                </button>
              </div>

              <div className="p-3.5 rounded-md bg-[#0E1116] border border-[#2A3441] flex items-center justify-between">
                <div className="space-y-0.5">
                  <div className="font-semibold text-[#E7E9EC]">PagerDuty On-Call</div>
                  <div className="text-[11px] text-[#6C7989]">Not configured</div>
                </div>
                <button className="px-2.5 py-1 rounded bg-[#3F6B8F] text-[#E7E9EC] hover:bg-[#4D7FA8]">
                  Connect
                </button>
              </div>

              <div className="p-3.5 rounded-md bg-[#0E1116] border border-[#2A3441] flex items-center justify-between">
                <div className="space-y-0.5">
                  <div className="font-semibold text-[#E7E9EC]">Jira Cloud Software</div>
                  <div className="text-[11px] text-[#4F8A73]">Connected (Project: ENG)</div>
                </div>
                <button className="px-2.5 py-1 rounded bg-[#1B222C] border border-[#2A3441] text-[#9CA6B2] hover:text-[#E7E9EC]">
                  Configure
                </button>
              </div>
            </div>
          </div>
        )}

        {/* TAB 4: CLI Tokens */}
        {activeTab === 'api' && (
          <div className="space-y-4 max-w-xl">
            <div>
              <h3 className="text-sm font-semibold text-[#E7E9EC]">
                CI/CD Scan Access Tokens
              </h3>
              <p className="text-xs text-[#9CA6B2]">
                Used by the `sonar-cli` runner in GitHub Actions, GitLab CI, and local pre-commit hooks.
              </p>
            </div>

            <div className="p-3.5 rounded-md bg-[#0E1116] border border-[#2A3441] space-y-2">
              <div className="text-[11px] text-[#9CA6B2] flex items-center justify-between">
                <span>Production CI Scanner Key</span>
                <span className="text-[#4F8A73]">Last used 12m ago</span>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="password"
                  readOnly
                  value="sonar_live_sec_993f48a17bc940e8a88192c7"
                  className="flex-1 px-3 py-1.5 rounded bg-[#151A21] border border-[#2A3441] text-xs text-[#8FB7D9] focus:outline-none"
                />
                <button
                  onClick={handleCopyCliToken}
                  className="flex items-center gap-1 px-3 py-1.5 rounded bg-[#1B222C] border border-[#2A3441] text-[#E7E9EC] hover:border-[#3F6B8F]"
                >
                  {copiedKey ? <Check className="w-3.5 h-3.5 text-[#4F8A73]" /> : <Copy className="w-3.5 h-3.5" />}
                  <span>{copiedKey ? 'Copied' : 'Copy'}</span>
                </button>
              </div>
            </div>
          </div>
        )}

        {/* TAB 5: Team */}
        {activeTab === 'team' && (
          <div className="space-y-4">
            <div>
              <h3 className="text-sm font-semibold text-[#E7E9EC]">
                Workspace Members & Security Roles
              </h3>
              <p className="text-xs text-[#9CA6B2]">
                Control who can suppress risk findings and override blocked CI/CD gates.
              </p>
            </div>

            <div className="divide-y divide-[#2A3441] border border-[#2A3441] rounded-md bg-[#0E1116] overflow-hidden">
              {[
                { name: 'Alexandre Sterling', role: 'VP Engineering (Gate Approver)', email: 'alex@codesonar.dev' },
                { name: 'Elena Rostova', role: 'Staff Security Engineer', email: 'elena@codesonar.dev' },
                { name: 'Devon Kowalski', role: 'Principal Architect', email: 'devon@codesonar.dev' },
                { name: 'Marcus Chen', role: 'Lead Backend Engineer', email: 'marcus@codesonar.dev' },
              ].map((member, i) => (
                <div key={i} className="p-3 flex items-center justify-between">
                  <div>
                    <div className="font-semibold text-[#E7E9EC]">{member.name}</div>
                    <div className="text-[11px] text-[#9CA6B2]">{member.email}</div>
                  </div>
                  <span className="px-2 py-0.5 rounded bg-[#1B222C] border border-[#2A3441] text-[11px] text-[#8FB7D9]">
                    {member.role}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
