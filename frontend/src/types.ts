export type Severity = 'critical' | 'high' | 'warning' | 'healthy' | 'info';

export type Category = 'security' | 'architecture' | 'reliability' | 'tech_debt' | 'compliance';

export type FindingStatus = 'open' | 'in_triage' | 'suppressed' | 'resolved';

export type Grade = 'A+' | 'A' | 'A-' | 'B+' | 'B' | 'B-' | 'C' | 'D' | 'F';

export interface Finding {
  id: string;
  ruleId: string;
  title: string;
  description: string;
  severity: Severity;
  category: Category;
  status: FindingStatus;
  filePath: string;
  lineRange: [number, number];
  codeSnippet: string;
  suggestedFix?: string;
  impactScore: number; // 1-100
  debtHours: number;
  blastRadius: 'isolated' | 'package' | 'cross_service' | 'system_wide';
  cwe?: string;
  cve?: string;
  author: string;
  commitHash: string;
  introducedDate: string;
  assignee?: {
    name: string;
    avatar: string;
    email: string;
  };
  repository: string;
  branch: string;
}

export interface RiskHotspot {
  id: string;
  filePath: string;
  repository: string;
  riskScore: number; // 1-100
  churnRate: 'high' | 'medium' | 'low';
  commitCount30d: number;
  authorsCount: number;
  cyclomaticComplexity: number;
  linesOfCode: number;
  findingsCount: {
    critical: number;
    high: number;
    warning: number;
  };
  testCoverage: number; // percentage
  blastRadiusScore: number;
  architecturalRole: string;
  refactorRoi: 'immediate' | 'high' | 'medium';
}

export interface WhatChangedEvent {
  id: string;
  type: 'pr_merged' | 'drift_detected' | 'finding_resolved' | 'gate_blocked' | 'cve_published' | 'refactor_completed';
  title: string;
  description: string;
  timestamp: string;
  actor: {
    name: string;
    avatar: string;
  };
  deltaScore: number; // e.g. -2.4 or +1.8
  prNumber?: number;
  commitHash?: string;
  affectedFile?: string;
  severity?: Severity;
}

export interface ArchitecturalDriftItem {
  id: string;
  title: string;
  type: 'layer_violation' | 'cyclic_dependency' | 'unauthorized_api' | 'orphaned_module' | 'license_risk';
  severity: Severity;
  sourceModule: string;
  targetModule: string;
  description: string;
  baselineRule: string;
  detectedAt: string;
  introducedInPR: string;
  status: 'active' | 'waived' | 'resolving';
  codeDiff?: {
    file: string;
    addedLines: string[];
    removedLines: string[];
  };
}

export interface ReleaseGateRecord {
  id: string;
  releaseTag: string;
  environment: 'production' | 'staging' | 'canary';
  status: 'passed' | 'blocked' | 'overridden';
  riskScore: number;
  criticalCount: number;
  highCount: number;
  timestamp: string;
  commitHash: string;
  evaluatedRules: {
    rule: string;
    passed: boolean;
    actualValue: string;
    threshold: string;
  }[];
  overriddenBy?: string;
  overrideReason?: string;
}

export interface RepositoryOption {
  id: string;
  name: string;
  branch: string;
  defaultBranch: string;
  lastScanned: string;
  overallScore: number;
  grade: Grade;
  activeFindings: number;
}

export interface QualityGatePolicy {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  blockProduction: boolean;
  metric: 'risk_score' | 'critical_findings' | 'high_findings' | 'new_drift' | 'test_coverage';
  operator: 'less_than' | 'greater_than' | 'equals_zero';
  threshold: number;
}
