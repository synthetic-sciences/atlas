import React from "react";

/* Line illustrations for the Atlas product sections. One language throughout:
   cream strokes on the warm-dark ground, sage for supported work, coral for
   what is running or chosen, dashed and faded for what was rejected. Labels
   are set in the page's serif at a size that stays legible. */

const fg = (a: number) => `hsl(var(--foreground) / ${a})`;
const CORAL = "hsl(14 72% 64%)";
const SAGE = "hsl(86 30% 62%)";
const REJECT = "hsl(8 45% 58%)";

type P = { x: number; y: number };
const curve = (a: P, b: P) => {
  const mx = (a.x + b.x) / 2;
  return `M ${a.x} ${a.y} C ${mx} ${a.y}, ${mx} ${b.y}, ${b.x} ${b.y}`;
};

export function Plate({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`atmosphere atmosphere-stars flex h-full w-full items-center justify-center p-5 sm:p-7 ${className}`}>
      {children}
    </div>
  );
}

function Label({ x, y, children, anchor = "middle", color = fg(0.82), size = 13 }: {
  x: number;
  y: number;
  children: React.ReactNode;
  anchor?: "start" | "middle" | "end";
  color?: string;
  size?: number;
}) {
  return (
    <text x={x} y={y} textAnchor={anchor} fontSize={size} fill={color}>
      {children}
    </text>
  );
}

function Node({ x, y, color, r = 6, hollow = false, halo = false, dashed = false }: {
  x: number;
  y: number;
  color: string;
  r?: number;
  hollow?: boolean;
  halo?: boolean;
  dashed?: boolean;
}) {
  return (
    <g>
      {halo ? <circle cx={x} cy={y} r={r * 2.4} fill={color} fillOpacity={0.16} className="animate-pulse" /> : null}
      <circle
        cx={x}
        cy={y}
        r={r}
        fill={hollow ? "hsl(var(--background))" : color}
        stroke={color}
        strokeWidth={1.4}
        strokeDasharray={dashed ? "2.5 2.5" : undefined}
      />
    </g>
  );
}

/* Atlas Graph: a question branching into hypotheses, runs and a claim. */
export function GraphHero() {
  const N = {
    q: { x: 70, y: 196 },
    a: { x: 230, y: 104 },
    b: { x: 230, y: 196 },
    c: { x: 230, y: 292 },
    a1: { x: 372, y: 70 },
    a2: { x: 372, y: 138 },
    e: { x: 500, y: 104 },
    b1: { x: 372, y: 196 },
    b2: { x: 372, y: 250 },
    c1: { x: 372, y: 318 },
  };
  const edge = (a: P, b: P, color: string, dashed = false, w = 1.3) => (
    <path d={curve(a, b)} fill="none" stroke={color} strokeWidth={w} strokeDasharray={dashed ? "4 4" : undefined} />
  );
  return (
    <svg viewBox="0 0 560 380" className="h-full w-full max-w-[560px]" role="img" aria-label="A research graph: a question branching into hypotheses, runs and a supported claim">
      {edge(N.q, N.a, fg(0.3))}
      {edge(N.q, N.b, fg(0.3))}
      {edge(N.q, N.c, REJECT, true)}
      {edge(N.a, N.a1, SAGE)}
      {edge(N.a, N.a2, SAGE)}
      {edge(N.a1, N.e, SAGE)}
      {edge(N.a2, N.e, SAGE)}
      {edge(N.b, N.b1, CORAL, false, 1.6)}
      {edge(N.b, N.b2, fg(0.25), true)}
      {edge(N.c, N.c1, REJECT, true)}

      <Node {...N.q} color={fg(0.9)} r={8} />
      <Node {...N.a} color={SAGE} />
      <Node {...N.a1} color={SAGE} r={5} />
      <Node {...N.a2} color={SAGE} r={5} />
      <rect x={N.e.x - 7} y={N.e.y - 7} width={14} height={14} transform={`rotate(45 ${N.e.x} ${N.e.y})`} fill={SAGE} />
      <Node {...N.b} color={CORAL} />
      <Node {...N.b1} color={CORAL} r={5} halo />
      <Node {...N.b2} color={fg(0.4)} r={5} hollow />
      <Node {...N.c} color={REJECT} hollow dashed />
      <Node {...N.c1} color={REJECT} r={5} hollow dashed />

      <Label x={40} y={150} anchor="start" size={14} color={fg(0.92)}>Does sparse attention</Label>
      <Label x={40} y={168} anchor="start" size={14} color={fg(0.92)}>hold at 32k tokens?</Label>
      <Label x={N.a.x} y={N.a.y - 16}>dense + sparse</Label>
      <Label x={N.b.x} y={N.b.y - 16}>head-dim sweep</Label>
      <Label x={N.c.x} y={N.c.y - 16} color={fg(0.5)}>windowed</Label>
      <Label x={N.a1.x} y={N.a1.y - 14} color={fg(0.6)} size={12}>run 12</Label>
      <Label x={N.a2.x} y={N.a2.y - 14} color={fg(0.6)} size={12}>run 13</Label>
      <Label x={N.b1.x} y={N.b1.y - 18} color={CORAL} size={12}>run 14</Label>
      <Label x={N.b2.x} y={N.b2.y - 14} color={fg(0.45)} size={12}>run 15</Label>
      <Label x={N.c1.x} y={N.c1.y - 14} color={fg(0.45)} size={12}>run 9</Label>
      <Label x={N.e.x} y={N.e.y - 18} color={SAGE}>claim holds</Label>

      <g fontSize={12}>
        <circle cx={44} cy={358} r={4} fill={SAGE} />
        <text x={54} y={362} fill={fg(0.6)}>supported</text>
        <circle cx={140} cy={358} r={4} fill={CORAL} />
        <text x={150} y={362} fill={fg(0.6)}>running</text>
        <circle cx={226} cy={358} r={4} fill="none" stroke={REJECT} strokeDasharray="2 2" />
        <text x={236} y={362} fill={fg(0.6)}>rejected</text>
      </g>
    </svg>
  );
}

/* GitHub for research: a paper's line of work stalls; a fork carries on. */
export function ForkVisual() {
  const up = [34, 92, 150, 208].map((x) => ({ x, y: 72 }));
  const fork = [208, 254, 296].map((x) => ({ x, y: 132 }));
  return (
    <svg viewBox="0 0 320 190" className="h-full w-full" role="img" aria-label="A forked research graph continuing past where the original stalled">
      {up.slice(1).map((p, i) => (
        <line key={i} x1={up[i].x} y1={72} x2={p.x} y2={72} stroke={fg(0.35)} strokeWidth={1.3} />
      ))}
      <line x1={208} y1={72} x2={240} y2={72} stroke={fg(0.25)} strokeWidth={1.3} strokeDasharray="3 4" />
      <path d={curve(up[2], fork[0])} fill="none" stroke={CORAL} strokeWidth={1.6} />
      {fork.slice(1).map((p, i) => (
        <line key={i} x1={fork[i].x} y1={132} x2={p.x} y2={132} stroke={CORAL} strokeWidth={1.6} />
      ))}
      {up.map((p, i) => (
        <Node key={i} {...p} color={fg(0.6)} r={5} hollow={i === 3} />
      ))}
      {fork.map((p, i) => (
        <Node key={i} {...p} color={CORAL} r={5} halo={i === fork.length - 1} />
      ))}
      <Label x={34} y={48} anchor="start" color={fg(0.6)}>the paper</Label>
      <Label x={208} y={48} color={fg(0.45)} size={12}>stalled</Label>
      <Label x={254} y={164} color={CORAL}>your fork</Label>
    </svg>
  );
}

/* Reproducible by default: the original curve and its rerun lie together. */
export function ReproduceVisual() {
  const pts = (phase: number, lift = 0) =>
    Array.from({ length: 27 }, (_, i) => {
      const t = i / 26;
      const x = 44 + t * 252;
      const y = 136 - 92 * Math.exp(-3.4 * t) + Math.sin(i * 1.7 + phase) * 2.6 * (1 - t * 0.6) - lift * t;
      return `${i ? "L" : "M"} ${x.toFixed(1)} ${y.toFixed(1)}`;
    }).join(" ");
  return (
    <svg viewBox="0 0 320 190" className="h-full w-full" role="img" aria-label="An original training curve and its rerun, overlapping">
      <line x1={44} y1={28} x2={44} y2={146} stroke={fg(0.2)} />
      <line x1={44} y1={146} x2={300} y2={146} stroke={fg(0.2)} />
      <path d={pts(0)} fill="none" stroke={fg(0.75)} strokeWidth={1.6} />
      <path d={pts(2.4, 7)} fill="none" stroke={CORAL} strokeWidth={1.6} strokeDasharray="5 4" />
      <Label x={44} y={20} anchor="start" color={fg(0.45)} size={12}>loss</Label>
      <Label x={300} y={162} anchor="end" color={fg(0.45)} size={12}>steps</Label>
      <g fontSize={12}>
        <line x1={196} y1={40} x2={214} y2={40} stroke={fg(0.75)} strokeWidth={1.6} />
        <text x={220} y={44} fill={fg(0.7)}>original</text>
        <line x1={196} y1={58} x2={214} y2={58} stroke={CORAL} strokeWidth={1.6} strokeDasharray="5 4" />
        <text x={220} y={62} fill={fg(0.7)}>rerun</text>
      </g>
      <path d="M 46 179 L 50 183 L 57 174" fill="none" stroke={SAGE} strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" />
      <Label x={64} y={183} anchor="start" color={SAGE} size={12}>claims reproduce</Label>
    </svg>
  );
}

/* Autoresearch at scale: a search tree, pruned branches, the best path. */
export function AutoresearchVisual() {
  const root = { x: 28, y: 96 };
  const l1 = [40, 96, 152].map((y) => ({ x: 96, y }));
  const l2 = [
    { x: 166, y: 24, p: 0 },
    { x: 166, y: 58, p: 0 },
    { x: 166, y: 84, p: 1 },
    { x: 166, y: 112, p: 1 },
    { x: 166, y: 140, p: 2 },
    { x: 166, y: 170, p: 2 },
  ];
  const l3 = [
    { x: 234, y: 50, p: 1 },
    { x: 234, y: 100, p: 3 },
    { x: 234, y: 126, p: 3 },
  ];
  const best = { x: 296, y: 126 };
  const pruned = (i: number) => i === 2;
  return (
    <svg viewBox="0 0 320 190" className="h-full w-full" role="img" aria-label="A search tree of experiments with pruned branches and the best path highlighted">
      {l1.map((n, i) => (
        <path key={i} d={curve(root, n)} fill="none" stroke={i === 1 ? CORAL : pruned(i) ? REJECT : fg(0.3)} strokeWidth={i === 1 ? 1.8 : 1.2} strokeDasharray={pruned(i) ? "3 3" : undefined} opacity={pruned(i) ? 0.7 : 1} />
      ))}
      {l2.map((n, i) => (
        <path key={i} d={curve(l1[n.p], n)} fill="none" stroke={i === 3 ? CORAL : pruned(n.p) ? REJECT : fg(0.25)} strokeWidth={i === 3 ? 1.8 : 1.1} strokeDasharray={pruned(n.p) ? "3 3" : undefined} opacity={pruned(n.p) ? 0.55 : 1} />
      ))}
      {l3.map((n, i) => (
        <path key={i} d={curve(l2[n.p], n)} fill="none" stroke={i === 2 ? CORAL : fg(0.25)} strokeWidth={i === 2 ? 1.8 : 1.1} />
      ))}
      <path d={curve(l3[2], best)} fill="none" stroke={CORAL} strokeWidth={1.8} />

      <Node {...root} color={fg(0.85)} r={5.5} />
      {l1.map((n, i) => (
        <Node key={i} {...n} r={4.5} color={i === 1 ? CORAL : pruned(i) ? REJECT : fg(0.5)} hollow={pruned(i)} dashed={pruned(i)} />
      ))}
      {l2.map((n, i) => (
        <Node key={i} {...n} r={3.8} color={i === 3 ? CORAL : pruned(n.p) ? REJECT : fg(0.45)} hollow={pruned(n.p)} dashed={pruned(n.p)} />
      ))}
      {l3.map((n, i) => (
        <Node key={i} {...n} r={3.8} color={i === 2 ? CORAL : fg(0.45)} />
      ))}
      <Node {...best} r={5.5} color={CORAL} halo />
      <Label x={best.x + 6} y={best.y + 28} anchor="end" color={CORAL}>best so far</Label>
    </svg>
  );
}
