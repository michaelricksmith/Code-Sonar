import React, { useState, useEffect } from 'react';
import {
  Terminal,
  Activity,
  CheckCircle2,
  AlertTriangle,
  Layers,
  Cpu,
  RefreshCw,
  X,
  Sparkles,
  Zap,
} from 'lucide-react';

interface LiveScanTerminalProps {
  isOpen: boolean;
  onClose: () => void;
  onScanComplete?: () => void;
}

export const LiveScanTerminal: React.FC<LiveScanTerminalProps> = ({
  isOpen,
  onClose,
  onScanComplete,
}) => {
  const [step, setStep] = useState(0);
  const [logs, setLogs] = useState<string[]>([]);
  const [progress, setProgress] = useState(12);

  const scanStages = [
    { text: '[INIT] Initializing Sonar AST Parser Engine v2.4 (V8 worker pool: 8 threads)...', delay: 150 },
    { text: '[VCS] Checking tree delta against main branch at HEAD (commit e8c47b9)...', delay: 300 },
    { text: '[TOKENIZER] Parsing 1,842 TypeScript and Go files into AST token trees...', delay: 500 },
    { text: '[GRAPH] Constructing directional dependency matrix (14,291 module edges)...', delay: 750 },
    { text: '[SECURITY] Evaluating analyzer rules: tainted dataflow, SQL injection, JWT validation...', delay: 1000 },
    { text: '[DRIFT] Checking boundary rules: prohibited Direct-DB call in src/services/billing...', delay: 1300 },
    { text: '[CYCLOMATIC] Computing McCabe complexity v(G) across all AST branch nodes...', delay: 1600 },
    { text: '[HOTSPOTS] Calculating composite risk index (Churn × Complexity / Test Coverage)...', delay: 1900 },
    { text: '[SARIF] Generating SARIF v2.1 diagnostics and calculating dynamic Risk Score...', delay: 2200 },
    { text: '[COMPLETED] Scan successful in 2.38s. All AST nodes synchronized.', delay: 2450 },
  ];

  useEffect(() => {
    if (!isOpen) {
      setLogs([]);
      setStep(0);
      setProgress(10);
      return;
    }

    let timeouts: NodeJS.Timeout[] = [];

    scanStages.forEach((stage, index) => {
      const timeout = setTimeout(() => {
        setLogs((prev) => [...prev, stage.text]);
        setStep(index + 1);
        setProgress(Math.min(100, Math.round(((index + 1) / scanStages.length) * 100)));

        if (index === scanStages.length - 1) {
          if (onScanComplete) onScanComplete();
        }
      }, stage.delay);
      timeouts.push(timeout);
    });

    return () => {
      timeouts.forEach((t) => clearTimeout(t));
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const isDone = progress === 100;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-in fade-in duration-150">
      <div className="w-full max-w-2xl bg-[#0B0E14] border border-[#2A3441] rounded-xl shadow-[0_0_50px_rgba(0,0,0,0.9)] overflow-hidden font-mono text-xs relative">
        {/* Glowing scanline sweep on modal */}
        <div className="absolute inset-0 pointer-events-none bg-[radial-gradient(#3F6B8F_1px,transparent_1px)] [background-size:16px_16px] opacity-20" />

        {/* Modal Top Bar */}
        <div className="px-4 py-3 bg-[#11161F] border-b border-[#222B38] flex items-center justify-between relative z-10">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-[#3F6B8F] animate-ping" />
            <span className="font-bold text-[#E7E9EC] text-xs">
              LIVE AST SCANNER TELEMETRY
            </span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#3F6B8F]/20 text-[#8FB7D9] border border-[#3F6B8F]/40">
              {isDone ? 'SCAN COMPLETE' : 'PROCESSING'}
            </span>
          </div>

          <button
            onClick={onClose}
            className="p-1 rounded text-[#9CA6B2] hover:text-[#E7E9EC] hover:bg-[#1B222C] transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Progress Bar & Telemetry Meters */}
        <div className="p-4 bg-[#11161F]/60 border-b border-[#222B38] space-y-2 relative z-10">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-[#8FB7D9]">AST Pipeline: Stage {step}/{scanStages.length}</span>
            <span className="font-bold text-[#E7E9EC]">{progress}%</span>
          </div>

          <div className="h-2 w-full bg-[#0B0E14] rounded-full overflow-hidden border border-[#222B38] relative">
            <div
              className="h-full bg-gradient-to-r from-[#3F6B8F] via-[#8FB7D9] to-[#4F8A73] transition-all duration-300 relative"
              style={{ width: `${progress}%` }}
            >
              <div className="absolute right-0 top-0 bottom-0 w-2 bg-white animate-pulse" />
            </div>
          </div>

          {/* Micro Telemetry chips */}
          <div className="grid grid-cols-4 gap-2 pt-1 text-[10px] text-[#6C7989]">
            <div className="bg-[#0B0E14] p-1.5 rounded border border-[#222B38]">
              <span className="block text-[#9CA6B2]">AST Nodes</span>
              <span className="text-[#8FB7D9] font-bold">248,192</span>
            </div>
            <div className="bg-[#0B0E14] p-1.5 rounded border border-[#222B38]">
              <span className="block text-[#9CA6B2]">Heap Used</span>
              <span className="text-[#E7E9EC] font-bold">142.8 MB</span>
            </div>
            <div className="bg-[#0B0E14] p-1.5 rounded border border-[#222B38]">
              <span className="block text-[#9CA6B2]">Rules Run</span>
              <span className="text-[#4F8A73] font-bold">142 evaluated</span>
            </div>
            <div className="bg-[#0B0E14] p-1.5 rounded border border-[#222B38]">
              <span className="block text-[#9CA6B2]">Latency</span>
              <span className="text-[#E8B468] font-bold">42ms/kLoc</span>
            </div>
          </div>
        </div>

        {/* Terminal Live Output Console */}
        <div className="p-4 bg-[#0B0E14] h-64 overflow-y-auto space-y-1.5 text-[11px] leading-relaxed relative z-10">
          {logs.map((log, i) => (
            <div key={i} className="flex items-start gap-2">
              <span className="text-[#3F6B8F] select-none">&gt;</span>
              <span
                className={
                  log.includes('[SECURITY]')
                    ? 'text-[#E07A7A]'
                    : log.includes('[DRIFT]')
                    ? 'text-[#E8B468]'
                    : log.includes('[COMPLETED]')
                    ? 'text-[#4F8A73] font-bold'
                    : 'text-[#9CA6B2]'
                }
              >
                {log}
              </span>
            </div>
          ))}

          {!isDone && (
            <div className="flex items-center gap-2 text-[#8FB7D9] animate-pulse">
              <span>&gt;</span>
              <span className="inline-block w-2 h-3.5 bg-[#8FB7D9]" />
            </div>
          )}
        </div>

        {/* Modal Footer Actions */}
        <div className="p-3 bg-[#11161F] border-t border-[#222B38] flex items-center justify-between relative z-10">
          <div className="text-[11px] text-[#6C7989]">
            {isDone ? 'Results loaded to memory.' : 'Parsing AST graphs in parallel...'}
          </div>

          <button
            onClick={onClose}
            className={`px-4 py-1.5 rounded text-xs font-semibold font-mono transition-colors ${
              isDone
                ? 'bg-[#3F6B8F] text-[#E7E9EC] hover:bg-[#4D7FA8]'
                : 'bg-[#1B222C] text-[#9CA6B2] border border-[#2A3441]'
            }`}
          >
            {isDone ? 'Close & View Updated Posture' : 'Run in Background'}
          </button>
        </div>
      </div>
    </div>
  );
};
