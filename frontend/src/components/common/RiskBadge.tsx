import React from 'react';
import { Severity, Grade, Category } from '../../types';
import { ShieldAlert, AlertTriangle, AlertCircle, CheckCircle2, Info, Network, ZapOff, Layers } from 'lucide-react';

interface SeverityBadgeProps {
  severity: Severity;
  showIcon?: boolean;
  className?: string;
  size?: 'sm' | 'md';
}

export const SeverityBadge: React.FC<SeverityBadgeProps> = ({
  severity,
  showIcon = true,
  className = '',
  size = 'md'
}) => {
  const config = {
    critical: {
      bg: 'bg-[#8F3D3D]/15',
      border: 'border-[#8F3D3D]/40',
      text: 'text-[#E07A7A]',
      icon: ShieldAlert,
      label: 'Critical',
    },
    high: {
      bg: 'bg-[#B85C4A]/15',
      border: 'border-[#B85C4A]/40',
      text: 'text-[#E58D7C]',
      icon: AlertTriangle,
      label: 'High Risk',
    },
    warning: {
      bg: 'bg-[#C28A3D]/15',
      border: 'border-[#C28A3D]/40',
      text: 'text-[#E8B468]',
      icon: AlertCircle,
      label: 'Warning',
    },
    healthy: {
      bg: 'bg-[#4F8A73]/15',
      border: 'border-[#4F8A73]/40',
      text: 'text-[#7CC4A8]',
      icon: CheckCircle2,
      label: 'Healthy',
    },
    info: {
      bg: 'bg-[#3F6B8F]/15',
      border: 'border-[#3F6B8F]/40',
      text: 'text-[#8FB7D9]',
      icon: Info,
      label: 'Info',
    },
  }[severity];

  const IconComponent = config.icon;
  const sizeClasses = size === 'sm' 
    ? 'px-1.5 py-0.5 text-[11px] gap-1' 
    : 'px-2 py-0.5 text-xs gap-1.5';

  return (
    <span
      className={`inline-flex items-center font-mono font-medium rounded-md border whitespace-nowrap ${config.bg} ${config.border} ${config.text} ${sizeClasses} ${className}`}
    >
      {showIcon && <IconComponent className={size === 'sm' ? "w-3 h-3" : "w-3.5 h-3.5"} />}
      <span>{config.label}</span>
    </span>
  );
};

interface GradeBadgeProps {
  grade: Grade;
  score?: number;
  size?: 'sm' | 'md' | 'lg' | 'xl';
}

export const GradeBadge: React.FC<GradeBadgeProps> = ({ grade, score, size = 'md' }) => {
  const getGradeStyle = () => {
    if (grade.startsWith('A')) {
      return {
        bg: 'bg-[#4F8A73]/20 text-[#7CC4A8] border-[#4F8A73]/50',
        ring: 'ring-1 ring-[#4F8A73]/30',
      };
    }
    if (grade.startsWith('B')) {
      return {
        bg: 'bg-[#3F6B8F]/20 text-[#8FB7D9] border-[#3F6B8F]/50',
        ring: 'ring-1 ring-[#3F6B8F]/30',
      };
    }
    if (grade.startsWith('C')) {
      return {
        bg: 'bg-[#C28A3D]/20 text-[#E8B468] border-[#C28A3D]/50',
        ring: 'ring-1 ring-[#C28A3D]/30',
      };
    }
    return {
      bg: 'bg-[#8F3D3D]/20 text-[#E07A7A] border-[#8F3D3D]/50',
      ring: 'ring-1 ring-[#8F3D3D]/30',
    };
  };

  const style = getGradeStyle();

  if (size === 'xl') {
    return (
      <div className={`flex flex-col items-center justify-center rounded-lg border font-mono ${style.bg} ${style.ring} p-3 w-16 h-16`}>
        <span className="text-2xl font-bold leading-none">{grade}</span>
        {score !== undefined && (
          <span className="text-[10px] opacity-80 mt-1">{score}/100</span>
        )}
      </div>
    );
  }

  if (size === 'lg') {
    return (
      <span className={`inline-flex items-center px-2.5 py-1 rounded-md border font-mono font-bold text-sm ${style.bg}`}>
        Grade {grade}
      </span>
    );
  }

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded border font-mono font-semibold text-xs ${style.bg}`}>
      {grade}
    </span>
  );
};

interface CategoryBadgeProps {
  category: Category;
  className?: string;
}

export const CategoryBadge: React.FC<CategoryBadgeProps> = ({ category, className = '' }) => {
  const config = {
    security: { label: 'Security', icon: ShieldAlert, color: 'text-[#E07A7A] bg-[#8F3D3D]/10 border-[#8F3D3D]/30' },
    architecture: { label: 'Architecture', icon: Network, color: 'text-[#E58D7C] bg-[#B85C4A]/10 border-[#B85C4A]/30' },
    reliability: { label: 'Reliability', icon: ZapOff, color: 'text-[#E8B468] bg-[#C28A3D]/10 border-[#C28A3D]/30' },
    tech_debt: { label: 'Tech Debt', icon: Layers, color: 'text-[#8FB7D9] bg-[#3F6B8F]/10 border-[#3F6B8F]/30' },
    compliance: { label: 'Compliance', icon: CheckCircle2, color: 'text-[#7CC4A8] bg-[#4F8A73]/10 border-[#4F8A73]/30' },
  }[category];

  const IconComp = config.icon;

  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 text-xs font-mono rounded-md border ${config.color} ${className}`}>
      <IconComp className="w-3 h-3" />
      <span>{config.label}</span>
    </span>
  );
};
