import { useEffect, useMemo, useRef, useState } from "react";
import heroMap from "@/assets/hero-map.webp";
import libraryList from "@/assets/library-list.png";
import libraryAdd from "@/assets/library-add.png";
import { AutoresearchVisual, ForkVisual, GraphHero, Plate, ReproduceVisual } from "@/components/visuals";

/* Logos are pre-processed greyscale-on-alpha PNGs served from /public/logos/.
   No runtime CSS filters needed. Translucency is one opacity property. */
const LOGOS = [
  { id: "harvard", src: "/logos/harvard.png", alt: "Harvard University" },
  { id: "mit", src: "/logos/mit.png", alt: "Massachusetts Institute of Technology" },
  { id: "stanford", src: "/logos/stanford.png", alt: "Stanford University" },
  { id: "fermilab", src: "/logos/fermilab.png", alt: "Fermilab" },
  { id: "yale", src: "/logos/yale.png", alt: "Yale University" },
  { id: "oxford", src: "/logos/oxford.png", alt: "University of Oxford" },
  { id: "nus", src: "/logos/nus.png", alt: "National University of Singapore" },
  { id: "iit-bombay", src: "/logos/iit-bombay.png", alt: "IIT Bombay" },
  { id: "iit-delhi", src: "/logos/iit-delhi.png", alt: "IIT Delhi" },
] as const;

/* Atlas. CMU Concrete throughout. Hyperspell-shaped layout. */

const H_HUGE = "text-[clamp(40px,5vw,72px)] leading-[1.02] tracking-[-0.024em]";
const H_BIG = "text-[clamp(30px,3.4vw,48px)] leading-[1.06] tracking-[-0.02em]";
const H_MED = "text-[22px] sm:text-[28px] leading-[1.14] tracking-[-0.012em]";
const P = "text-[14px] leading-[1.7] text-foreground/75";
const P_BIG = "text-[16px] sm:text-[17px] leading-[1.7] text-foreground/75";
const LABEL = "text-[14px] text-muted-foreground";

/* Eyebrow - a quiet product label above a heading. Same face as the body
   text; no rules, no numerals, no mono. */
function Eyebrow({
  children,
  className = "",
  tone = "muted",
}: {
  children: React.ReactNode;
  className?: string;
  tone?: "muted" | "bright";
}) {
  const text = tone === "bright" ? "text-foreground/70" : "text-foreground/55";
  return (
    <div className={`flex items-center ${className}`}>
      <span className={`text-[14px] tracking-[0.04em] ${text}`}>{children}</span>
    </div>
  );
}

/* Cta - the one button system used everywhere. Sharp corners on purpose;
   the arrow nudges right on hover. */
function Cta({
  children,
  href = "#",
  variant = "primary",
  arrow = true,
  className = "",
}: {
  children: React.ReactNode;
  href?: string;
  variant?: "primary" | "ghost";
  arrow?: boolean;
  className?: string;
}) {
  const base =
    "group/cta inline-flex items-center justify-center gap-2.5 h-11 px-6 text-[14px] leading-none select-none";
  const look =
    variant === "primary"
      ? "btn-primary"
      : "border border-foreground/25 text-foreground/90 hover:border-foreground/55 hover:bg-foreground/[0.04] backdrop-blur-[2px] transition-colors duration-300";
  return (
    <a href={href} className={`${base} ${look} ${className}`}>
      {children}
      {arrow ? (
        <svg
          width="14"
          height="10"
          viewBox="0 0 14 10"
          aria-hidden
          className="transition-transform duration-300 group-hover/cta:translate-x-[3px]"
        >
          <path d="M0 5h12M8.5 1 13 5l-4.5 4" stroke="currentColor" strokeWidth="1.2" fill="none" />
        </svg>
      ) : null}
    </a>
  );
}

/* InstallChip - copyable install command. Click to copy, icon confirms. */
function InstallChip({ className = "" }: { className?: string }) {
  const [copied, setCopied] = useState(false);
  const cmd = "npm i -g @synsci/atlas";
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard?.writeText(cmd).catch(() => {});
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1600);
      }}
      className={`group/chip inline-flex items-center gap-3 border border-border/70 bg-background/45 backdrop-blur-[3px] pl-4 pr-3 h-11 font-terminal text-[13px] text-foreground/80 hover:border-foreground/35 hover:text-foreground transition-colors duration-300 cursor-pointer ${className}`}
      aria-label="Copy install command"
    >
      <span className="text-foreground/40">$</span>
      {cmd}
      <span className="ml-1 text-foreground/40 group-hover/chip:text-foreground/75 transition-colors" aria-hidden>
        {copied ? (
          <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
            <path d="M2.5 7 5 9.5 10.5 3.5" stroke="hsl(86 30% 60%)" strokeWidth="1.4" />
          </svg>
        ) : (
          <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
            <rect x="4" y="4" width="7" height="7" stroke="currentColor" />
            <path d="M9 4V2H2v7h2" stroke="currentColor" fill="none" />
          </svg>
        )}
      </span>
    </button>
  );
}

/* ---------------------------- ASCII backdrop ---------------------------- */

function useAsciiContours(cols: number, rows: number, seed = 1) {
  return useMemo(() => {
    const RAMP = [" ", " ", ".", ".", ",", ":", ";", "-", "~", "+", "=", "o", "0", "#"];
    const peaks = [
      { x: cols * 0.28, y: rows * 0.42, s: cols * 0.22, h: 1.0 },
      { x: cols * 0.72, y: rows * 0.38, s: cols * 0.18, h: 0.85 },
      { x: cols * 0.55, y: rows * 0.82, s: cols * 0.30, h: 0.55 },
    ];
    let out = "";
    for (let y = 0; y < rows; y++) {
      let line = "";
      for (let x = 0; x < cols; x++) {
        let v = 0;
        for (const p of peaks) {
          const dx = (x - p.x) / p.s;
          const dy = ((y - p.y) * 1.9) / p.s;
          v += p.h * Math.exp(-(dx * dx + dy * dy));
        }
        const n = (Math.sin((x * 12.9898 + y * 78.233 + seed) * 0.5) + 1) * 0.04;
        v = Math.max(0, Math.min(0.999, v + n));
        line += RAMP[Math.floor(v * RAMP.length)];
      }
      out += line + "\n";
    }
    return out;
  }, [cols, rows, seed]);
}

function AsciiBackdrop({ seed = 1, opacity = "text-foreground/[0.06]" }: { seed?: number; opacity?: string }) {
  const art = useAsciiContours(220, 80, seed);
  return (
    <pre aria-hidden className={`ascii absolute inset-0 m-0 p-0 text-[10px] leading-[1.05] ${opacity} vignette`}>
      {art}
    </pre>
  );
}

/* ------------------------------- Reveal -------------------------------- */

function Reveal({ children, delay = 0, className = "" }: { children: React.ReactNode; delay?: number; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            setShown(true);
            obs.disconnect();
          }
        }
      },
      { threshold: 0.12, rootMargin: "0px 0px -8% 0px" }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, []);
  return (
    <div
      ref={ref}
      style={{ transitionDelay: `${delay}ms` }}
      className={`transition-all duration-[1100ms] ease-[cubic-bezier(0.19,1,0.22,1)] will-change-transform ${
        shown ? "opacity-100 translate-y-0 blur-0" : "opacity-0 translate-y-6 blur-[5px]"
      } ${className}`}
    >
      {children}
    </div>
  );
}

/* ----------------------------- Section frame ---------------------------- */

function Section({ children, className = "", grain = false, seed = 1, id }: { children: React.ReactNode; className?: string; grain?: boolean; seed?: number; id?: string }) {
  return (
    <section id={id} className={`relative w-full overflow-hidden border-t border-border/40 ${grain ? "grain" : ""}`}>
      <div className="absolute inset-0 graticule opacity-[0.04]" />
      <AsciiBackdrop seed={seed} />
      <div className={`relative z-10 mx-auto max-w-[1400px] w-full px-6 sm:px-10 ${className}`}>
        {children}
    </div>
    </section>
  );
}

/* ---------------------- Atlas web app UI mockup ------------------------- */
/*
  A polished mockup of what the Atlas web view looks like. Window chrome,
  left-side tree, right-side detail pane. Same example data shown on hero,
  trust block, and terminal. No floating diagrams.
*/

type State = "open" | "running" | "supported" | "needs-evidence" | "rejected" | "hypothesis";
const stateClass: Record<State, string> = {
  open: "text-foreground/55",
  running: "text-[hsl(38,55%,72%)]",
  supported: "text-[hsl(86,30%,62%)]",
  "needs-evidence": "text-[hsl(28,55%,68%)]",
  rejected: "text-[hsl(8,55%,65%)]",
  hypothesis: "text-foreground/65",
};

type TreeRow = { id: string; label: string; depth: number; state?: State; active?: boolean; muted?: boolean };

const tree: TreeRow[] = [
  { id: "m_8a2f3c", label: "cross-encoder reranking", depth: 0, muted: true },
  { id: "q_7c1f2a", label: "is reranking helpful?", depth: 1, state: "open" },
  { id: "n_4d8e1b2", label: "try cross-encoder reranker", depth: 2, state: "running", active: true },
  { id: "n_e92b4c", label: "open objections to method", depth: 3, state: "needs-evidence" },
  { id: "n_b80fa1", label: "bm25 baseline holds", depth: 2, state: "supported" },
  { id: "q_22ac01", label: "what is the failure mode?", depth: 1, state: "open" },
];

function TreeRowEl({ row }: { row: TreeRow }) {
  return (
    <li
      className={`group flex items-center gap-3 px-3 py-1.5 -mx-3 border-l-2 ${
        row.active ? "border-foreground/45 bg-background/55" : "border-transparent hover:bg-background/30"
      }`}
    >
      <span style={{ width: row.depth * 16 }} className="shrink-0" />
      <span
        className={`text-[11px] tabular-nums shrink-0 ${
          row.muted ? "text-foreground/35" : row.active ? "text-foreground/65" : "text-foreground/40"
        }`}
      >
        {row.id}
      </span>
      <span
        className={`flex-1 truncate text-[13px] ${
          row.muted ? "text-foreground/45" : row.active ? "text-foreground" : "text-foreground/80"
        }`}
      >
        {row.label}
      </span>
      {row.state ? (
        <span className={`text-[11px] shrink-0 ${stateClass[row.state]}`}>[{row.state}]</span>
      ) : null}
    </li>
  );
}

/* ----------------------- Atmosphere shell + pill label ----------------------- */
/*
  VisualShell wraps every illustration on the landing page in a Hyperspell-
  style atmospheric backdrop: wispy light trails, grain, optional star field,
  and a bordered pill label anchored to the top-left.
*/

/* AtlasMark - a compass rose. Coral north needle, cream south, faint
   east-west arms inside a thin ring. */
function AtlasMark({ size = 10 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden
      className="text-foreground/85"
    >
      <circle cx="8" cy="8" r="6.7" stroke="currentColor" strokeWidth="1.1" />
      <path d="M3.6 8 L8 6.9 L12.4 8 L8 9.1 Z" fill="currentColor" opacity="0.45" />
      <path d="M8 2.9 L9.25 8 L6.75 8 Z" fill="hsl(var(--accent-coral))" />
      <path d="M8 13.1 L9.25 8 L6.75 8 Z" fill="currentColor" />
    </svg>
  );
}

function VisualPill({
  children,
  icon,
  variant = "bordered",
  dot = false,
}: {
  children: React.ReactNode;
  icon?: React.ReactNode;
  variant?: "bordered" | "plain";
  dot?: boolean;
}) {
  const cls = variant === "bordered" ? "visual-pill" : "visual-pill-plain";
  return (
    <div className={cls}>
      {dot ? <span className="visual-pill-dot" aria-hidden /> : null}
      {icon ? <span className="shrink-0">{icon}</span> : null}
      <span>{children}</span>
    </div>
  );
}

function VisualShell({
  label,
  pillIcon,
  pillVariant = "bordered",
  pillDot = false,
  stars = false,
  className = "",
  innerClassName = "",
  align = "center",
  children,
}: {
  label?: React.ReactNode;
  pillIcon?: React.ReactNode;
  pillVariant?: "bordered" | "plain";
  pillDot?: boolean;
  stars?: boolean;
  className?: string;
  innerClassName?: string;
  align?: "start" | "center";
  children: React.ReactNode;
}) {
  const atm = stars ? "atmosphere atmosphere-stars" : "atmosphere";
  const justify = align === "start" ? "justify-start" : "justify-center";
  return (
    <div className={`${atm} h-full w-full flex flex-col ${className}`}>
      {label ? (
        <div className="px-4 pt-4">
          <VisualPill icon={pillIcon} variant={pillVariant} dot={pillDot}>
            {label}
          </VisualPill>
        </div>
      ) : null}
      <div className={`flex-1 flex flex-col ${justify} px-4 pb-4 pt-3 ${innerClassName}`}>
        {children}
      </div>
    </div>
  );
}

/* ----------------------- Mini visuals (used in cards) ----------------------- */

function MiniTree() {
  return (
    <div className="font-terminal text-[12px] leading-[1.85] text-foreground/75">
      <div><span className="text-foreground/40">m_8a2f3c</span>  cross-encoder reranking</div>
      <div><span className="text-foreground/35">├─</span> <span className="text-foreground/40">q_7c1f2a</span>  is reranking helpful?    <span className={stateClass.open}>[open]</span></div>
      <div><span className="text-foreground/35">│  ├─</span> <span className="text-foreground/40">n_4d8e</span>    cross-encoder         <span className={stateClass.running}>[running]</span></div>
      <div><span className="text-foreground/35">│  ├─</span> <span className="text-foreground/40">n_b80f</span>    bm25 baseline         <span className={stateClass.supported}>[supported]</span></div>
      <div><span className="text-foreground/35">│  └─</span> <span className="text-foreground/40">n_e92b</span>    open objections       <span className={stateClass["needs-evidence"]}>[needs-evidence]</span></div>
      <div><span className="text-foreground/35">└─</span> <span className="text-foreground/40">q_22ac01</span> failure mode?           <span className={stateClass.open}>[open]</span></div>
    </div>
  );
}

function MiniTerminal() {
  return (
    <div className="font-terminal text-[12px] leading-[1.85] whitespace-pre">
      <div><span className="text-foreground/40">$</span> atlas init <span className="text-[hsl(36,42%,76%)]">"is reranking helpful?"</span></div>
      <div className="text-foreground/55"><span className={stateClass.supported}>+</span> map <span className="text-[hsl(38,58%,72%)]">m_8a2f3c</span> initialized</div>
      <div className="text-foreground/55"><span className={stateClass.supported}>+</span> root <span className="text-[hsl(38,58%,72%)]">q_7c1f2a</span> [open]</div>
      <div><span className="text-foreground/40">$</span> atlas branch <span className="text-[hsl(38,58%,72%)]">q_7c1f2a</span> <span className="text-[hsl(36,42%,76%)]">"cross-encoder"</span></div>
      <div className="text-foreground/55"><span className={stateClass.supported}>+</span> branched <span className="text-[hsl(38,58%,72%)]">n_4d8e1b2</span> [hypothesis]</div>
      <div><span className="text-foreground/40">$</span><span className="terminal-cursor" /></div>
    </div>
  );
}

function MiniClaim() {
  return (
    <div className="border border-border/40 bg-background/40 p-4 sm:p-5">
      <div className="text-[11px] font-terminal tabular-nums text-foreground/40">n_4d8e1b2  claim</div>
      <div className="mt-1.5 text-[14px] leading-snug">try cross-encoder reranker</div>
      <div className={`mt-1.5 text-[12px] font-terminal ${stateClass.supported}`}>[supported]</div>
      <div className="mt-4 pt-3 border-t border-border/30">
        <div className="text-[11px] text-foreground/40 mb-2">Evidence</div>
        <ul className="space-y-1.5 text-[12px] font-terminal">
          <li className="flex items-center justify-between">
            <span className="text-foreground/75">run_a93f.json</span>
            <span className={stateClass.supported}>passed</span>
          </li>
          <li className="flex items-center justify-between">
            <span className="text-foreground/75">plot_2c1.png</span>
            <span className={stateClass.supported}>ok</span>
          </li>
          <li className="flex items-center justify-between">
            <span className="text-foreground/75">cordy v0.6.2</span>
            <span className={stateClass.supported}>linked</span>
          </li>
        </ul>
      </div>
    </div>
  );
}

function MiniHistory() {
  return (
    <div className="font-terminal text-[12px] leading-[1.85]">
      <div><span className="text-foreground/40 tabular-nums">@2.4d</span> <span className="text-foreground/75">branched </span><span className="text-foreground/45">n_4d8e</span> <span className="text-foreground/55">cross-encoder</span></div>
      <div><span className="text-foreground/40 tabular-nums">@1.8d</span> <span className="text-foreground/75">attached</span> <span className="text-foreground/55">run_a93f.json</span></div>
      <div><span className="text-foreground/40 tabular-nums">@1.2d</span> <span className="text-foreground/75">rejected </span><span className="text-foreground/45">n_b80f.alt</span></div>
      <div><span className="text-foreground/40 tabular-nums">@0.6d</span> <span className="text-foreground/75">objected </span><span className="text-foreground/45">n_e92b</span> <span className="text-foreground/55">latency</span></div>
      <div><span className="text-foreground/40 tabular-nums">@0.3d</span> <span className="text-foreground/75">defended</span> <span className="text-foreground/45">n_4d8e</span> <span className={stateClass.supported}>[supported]</span></div>
      <div className="mt-3 pt-2 border-t border-border/30 text-foreground/45">
        atlas checkout @1.8d  to restore prior state
      </div>
    </div>
  );
}

/* ----------------------- Hyperspell-style product visuals ----------------------- */

/* SystemDiagram - High-fidelity SVG diagram with a technical/terminal aesthetic.
   Represents a version-controlled research graph. Height is locked to the
   neighbor dither box (440px) so the row reads as a balanced pair. */
function SystemDiagram() {
  return (
    <div className="atmosphere atmosphere-stars w-full h-[440px] flex flex-col">
      <div className="px-5 pt-5 flex items-center justify-between gap-3">
        <VisualPill icon={<AtlasMark />}>atlas map / sparse-attn</VisualPill>
        <span className="visual-pill-plain">3 branches / 1 running</span>
      </div>
      <div className="flex-1 flex items-center justify-center px-6 sm:px-8 pb-6 pt-3 min-h-0">
      <svg
        viewBox="0 0 500 360"
        preserveAspectRatio="xMidYMid meet"
        className="w-full h-full font-terminal text-[11px]"
      >
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="hsl(var(--foreground) / 0.3)" />
          </marker>
          <marker id="arrow-active" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="hsl(86, 30%, 62%)" />
          </marker>
        </defs>

        {/* Grid lines for tech feel */}
        <pattern id="smallGrid" width="20" height="20" patternUnits="userSpaceOnUse">
          <path d="M 20 0 L 0 0 0 20" fill="none" stroke="hsl(var(--foreground) / 0.03)" strokeWidth="0.5" />
        </pattern>
        <rect width="100%" height="100%" fill="url(#smallGrid)" />

        {/* Connection Lines */}
        <path d="M 250 70 L 250 110 L 130 110 L 130 140" fill="none" stroke="hsl(var(--foreground) / 0.3)" strokeWidth="1" markerEnd="url(#arrow)" />
        <path d="M 250 70 L 250 110 L 370 110 L 370 140" fill="none" stroke="hsl(86, 30%, 62%)" strokeWidth="1" markerEnd="url(#arrow-active)" />
        <path d="M 370 200 L 370 250" fill="none" stroke="hsl(var(--foreground) / 0.3)" strokeWidth="1" markerEnd="url(#arrow)" />
        <path d="M 130 200 L 130 240" fill="none" stroke="hsl(var(--foreground) / 0.3)" strokeWidth="1" strokeDasharray="3 3" />

        {/* Root Node */}
        <g transform="translate(130, 20)">
          <rect x="0" y="0" width="240" height="50" rx="4" fill="hsl(var(--background) / 0.8)" stroke="hsl(var(--foreground) / 0.2)" strokeWidth="1" />
          <rect x="0" y="0" width="4" height="50" rx="2" fill="hsl(var(--foreground) / 0.4)" />
          <text x="16" y="20" fill="hsl(var(--foreground) / 0.5)" fontSize="10">commit: 8a2f3c</text>
          <text x="16" y="36" fill="hsl(var(--foreground) / 0.9)">does sparse attn preserve recall?</text>
        </g>

        {/* Branch A - running. Coral accent matches Hyperspell-style hot points. */}
        <g transform="translate(30, 140)">
          <rect x="0" y="0" width="200" height="60" rx="4" fill="hsl(var(--background) / 0.8)" stroke="hsl(14, 70%, 60% / 0.5)" strokeWidth="1" />
          <rect x="0" y="0" width="4" height="60" rx="2" fill="hsl(14, 75%, 62%)" />
          <text x="16" y="20" fill="hsl(var(--foreground) / 0.5)" fontSize="10">branch: windowed</text>
          <text x="16" y="36" fill="hsl(var(--foreground) / 0.9)">swap to local windowed attn</text>
          <text x="16" y="50" fill="hsl(14, 75%, 68%)" fontSize="10">[running]</text>
          {/* Coral pulse - soft halo behind the dot. */}
          <circle cx="180" cy="30" r="11" fill="hsl(14, 75%, 60% / 0.35)" />
          <circle cx="180" cy="30" r="6" fill="hsl(14, 75%, 60% / 0.55)" />
          <circle cx="180" cy="30" r="4" fill="hsl(14, 75%, 65%)" className="animate-pulse" />
        </g>

        {/* Branch B */}
        <g transform="translate(270, 140)">
          <rect x="0" y="0" width="200" height="60" rx="4" fill="hsl(var(--background) / 0.8)" stroke="hsl(86, 30%, 62% / 0.4)" strokeWidth="1" />
          <rect x="0" y="0" width="4" height="60" rx="2" fill="hsl(86, 30%, 62%)" />
          <text x="16" y="20" fill="hsl(var(--foreground) / 0.5)" fontSize="10">branch: dense-sparse</text>
          <text x="16" y="36" fill="hsl(var(--foreground) / 0.9)">mix dense + sparse heads</text>
          <text x="16" y="50" fill="hsl(86, 30%, 62%)" fontSize="10">[supported]</text>
          <path d="M 175 30 L 180 35 L 190 25" fill="none" stroke="hsl(86, 30%, 62%)" strokeWidth="2" />
        </g>

        {/* Child of B */}
        <g transform="translate(270, 250)">
          <rect x="0" y="0" width="200" height="60" rx="4" fill="hsl(var(--background) / 0.8)" stroke="hsl(var(--foreground) / 0.2)" strokeWidth="1" />
          <rect x="0" y="0" width="4" height="60" rx="2" fill="hsl(28, 55%, 68%)" />
          <text x="16" y="20" fill="hsl(var(--foreground) / 0.5)" fontSize="10">commit: e92b4c</text>
          <text x="16" y="36" fill="hsl(var(--foreground) / 0.9)">ablation on head dim</text>
          <text x="16" y="50" fill="hsl(28, 55%, 68%)" fontSize="10">[needs evidence]</text>
        </g>

        {/* More indicator */}
        <g transform="translate(130, 250)">
          <circle cx="0" cy="0" r="3" fill="hsl(var(--foreground) / 0.3)" />
          <circle cx="0" cy="12" r="3" fill="hsl(var(--foreground) / 0.2)" />
          <circle cx="0" cy="24" r="3" fill="hsl(var(--foreground) / 0.1)" />
        </g>
      </svg>
      </div>
    </div>
  );
}

/* Starburst - the radiant icon used at the top of the system diagram and on the Network graph. */
function Starburst({ size = 36, className = "" }: { size?: number; className?: string }) {
  const cx = size / 2;
  const cy = size / 2;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className={className} aria-hidden>
      <g stroke="currentColor" strokeWidth="1" strokeLinecap="round">
        {Array.from({ length: 12 }).map((_, i) => {
          const a = (i * Math.PI) / 6;
          const r1 = size * (i % 2 === 0 ? 0.18 : 0.12);
          const r2 = size * 0.46;
          const x1 = cx + Math.cos(a) * r1;
          const y1 = cy + Math.sin(a) * r1;
          const x2 = cx + Math.cos(a) * r2;
          const y2 = cy + Math.sin(a) * r2;
          return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} />;
        })}
      </g>
      <circle cx={cx} cy={cy} r={size * 0.04} fill="currentColor" />
    </svg>
  );
}

function FlowArrow() {
  return (
    <div className="flex justify-center py-3 text-foreground/45">
      <svg width="14" height="22" viewBox="0 0 14 22" aria-hidden>
        <line x1="7" y1="0" x2="7" y2="16" stroke="currentColor" strokeWidth="1" />
        <polygon points="7,21 2,14 12,14" fill="currentColor" />
      </svg>
    </div>
  );
}

function SmallArrowUp() {
  return (
    <div className="flex justify-center">
      <svg width="10" height="16" viewBox="0 0 10 16" aria-hidden>
        <line x1="5" y1="2" x2="5" y2="14" stroke="currentColor" strokeWidth="1" />
        <polygon points="5,0 0,6 10,6" fill="currentColor" />
      </svg>
    </div>
  );
}

/* Source-icon glyphs - minimal, line-only SVGs sized 18x18.
   Used in the SystemDiagram and SourcesGrid. */
function PaperIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden className="text-foreground/75">
      <rect x="3.5" y="2.5" width="11" height="13" stroke="currentColor" />
      <line x1="6" y1="6" x2="12" y2="6" stroke="currentColor" />
      <line x1="6" y1="9" x2="12" y2="9" stroke="currentColor" />
      <line x1="6" y1="12" x2="10" y2="12" stroke="currentColor" />
    </svg>
  );
}
function RepoIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden className="text-foreground/75">
      <rect x="2.5" y="3" width="13" height="12" rx="1" stroke="currentColor" />
      <line x1="2.5" y1="6.5" x2="15.5" y2="6.5" stroke="currentColor" />
      <circle cx="5" cy="4.7" r="0.7" fill="currentColor" />
    </svg>
  );
}
function RunIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden className="text-foreground/75">
      <polyline points="2.5,13 6,9 9,11 12,5 15.5,8" stroke="currentColor" fill="none" />
      <line x1="2.5" y1="15.5" x2="15.5" y2="15.5" stroke="currentColor" />
    </svg>
  );
}
function NoteIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden className="text-foreground/75">
      <polyline points="3.5,2.5 11.5,2.5 14.5,5.5 14.5,15.5 3.5,15.5 3.5,2.5" stroke="currentColor" />
      <line x1="6" y1="9" x2="12" y2="9" stroke="currentColor" />
      <line x1="6" y1="12" x2="11" y2="12" stroke="currentColor" />
    </svg>
  );
}
function GitIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden className="text-foreground/75">
      <circle cx="5" cy="4.5" r="1.5" stroke="currentColor" />
      <circle cx="5" cy="13.5" r="1.5" stroke="currentColor" />
      <circle cx="13" cy="9" r="1.5" stroke="currentColor" />
      <line x1="5" y1="6" x2="5" y2="12" stroke="currentColor" />
      <path d="M5 9 Q 5 9 13 9" stroke="currentColor" fill="none" />
    </svg>
  );
}
function DataIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden className="text-foreground/75">
      <ellipse cx="9" cy="4.5" rx="5" ry="2" stroke="currentColor" />
      <path d="M4 4.5 V 9 a 5 2 0 0 0 10 0 V 4.5" stroke="currentColor" fill="none" />
      <path d="M4 9 V 13.5 a 5 2 0 0 0 10 0 V 9" stroke="currentColor" fill="none" />
    </svg>
  );
}
function PlotIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden className="text-foreground/75">
      <line x1="2.5" y1="2.5" x2="2.5" y2="15.5" stroke="currentColor" />
      <line x1="2.5" y1="15.5" x2="15.5" y2="15.5" stroke="currentColor" />
      <rect x="4.5" y="11" width="2" height="4" fill="currentColor" />
      <rect x="8" y="7" width="2" height="8" fill="currentColor" />
      <rect x="11.5" y="9" width="2" height="6" fill="currentColor" />
    </svg>
  );
}
function CalendarIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden className="text-foreground/75">
      <rect x="2.5" y="4" width="13" height="11" stroke="currentColor" />
      <line x1="2.5" y1="7.5" x2="15.5" y2="7.5" stroke="currentColor" />
      <line x1="6" y1="2.5" x2="6" y2="5" stroke="currentColor" />
      <line x1="12" y1="2.5" x2="12" y2="5" stroke="currentColor" />
    </svg>
  );
}

/* NetworkGraph - Hyperspell's "Agentic Memory Network" visual.
   White starburst nodes on dark, connected by faint lines. */
function NetworkGraph() {
  // Pre-positioned to look organic but balanced.
  const nodes = [
    { x: 90, y: 60, big: true },
    { x: 35, y: 120, big: false },
    { x: 145, y: 30, big: false },
    { x: 215, y: 90, big: true },
    { x: 290, y: 50, big: false },
    { x: 270, y: 145, big: false },
    { x: 175, y: 165, big: false },
    { x: 80, y: 195, big: false },
    { x: 150, y: 110, big: false },
    { x: 225, y: 175, big: false },
  ];
  const edges: [number, number][] = [
    [0, 1], [0, 2], [0, 8], [2, 3], [3, 4], [3, 5], [3, 8],
    [5, 6], [5, 9], [6, 7], [7, 1], [8, 1], [8, 6], [4, 3],
  ];
  return (
    <svg viewBox="0 0 340 220" className="w-full h-full" aria-hidden>
      {edges.map(([a, b], i) => (
        <line
          key={i}
          x1={nodes[a].x}
          y1={nodes[a].y}
          x2={nodes[b].x}
          y2={nodes[b].y}
          stroke="hsl(var(--foreground) / 0.25)"
          strokeWidth="0.7"
        />
      ))}
      {nodes.map((n, i) => (
        <g key={i} transform={`translate(${n.x} ${n.y})`}>
          <circle r={n.big ? 14 : 9} fill="hsl(var(--foreground) / 0.05)" />
          {Array.from({ length: 8 }).map((_, k) => {
            const a = (k * Math.PI) / 4;
            const r = n.big ? 10 : 6;
            return (
              <line
                key={k}
                x1={0}
                y1={0}
                x2={Math.cos(a) * r}
                y2={Math.sin(a) * r}
                stroke="hsl(var(--foreground))"
                strokeWidth={n.big ? 0.9 : 0.6}
                strokeLinecap="round"
              />
            );
          })}
          <circle r={n.big ? 1.6 : 1.1} fill="hsl(var(--foreground))" />
        </g>
      ))}
      {/* Floating tag */}
      <g transform="translate(160 100)">
        <rect x="-58" y="-13" width="116" height="22" fill="hsl(var(--background) / 0.85)" stroke="hsl(var(--foreground) / 0.4)" />
        <text
          x="0"
          y="0"
          dominantBaseline="middle"
          textAnchor="middle"
          fontFamily="JetBrains Mono, monospace"
          fontSize="9"
          fill="hsl(var(--foreground))"
          letterSpacing="0.5"
        >
          atlas memory map
        </text>
      </g>
      {/* Floating callout in upper-left */}
      <g transform="translate(40 30)">
        <rect x="-32" y="-10" width="64" height="18" fill="hsl(var(--background) / 0.85)" stroke="hsl(var(--foreground) / 0.4)" />
        <text
          x="0"
          y="0"
          dominantBaseline="middle"
          textAnchor="middle"
          fontFamily="JetBrains Mono, monospace"
          fontSize="8"
          fill="hsl(var(--foreground) / 0.85)"
        >
          ask anything
        </text>
      </g>
    </svg>
  );
}

/* FlowDiagram - Hyperspell's "Continuous Learning" visual.
   Cards on the left flowing through a central "UPDATING MEMORY" pill into "WORKS AS A TEAM MANAGER". */
function FlowDiagram() {
  return (
    <div className="relative grid-paper px-5 py-6 min-h-[280px]">
      <div className="grid grid-cols-12 gap-3 items-center">
        {/* Left: stacked tasks */}
        <div className="col-span-5 space-y-2">
          <div className="border border-border/50 bg-background/60 px-3 py-2 font-terminal text-[10px] leading-tight text-foreground/80">
            <div className="text-foreground/40 mb-0.5">2.4d ago</div>
            cross-encoder reranking
          </div>
          <div className="border border-border/50 bg-background/60 px-3 py-2 font-terminal text-[10px] leading-tight text-foreground/80">
            <div className="text-foreground/40 mb-0.5">today 11:32</div>
            objections to short-query latency
          </div>
          <div className="border border-border/50 bg-background/60 px-3 py-2 font-terminal text-[10px] leading-tight text-foreground/80">
            <div className="text-foreground/40 mb-0.5">today 11:34</div>
            evidence: bench/short.py
          </div>
        </div>

        {/* Arrows */}
        <div className="col-span-1 flex flex-col items-center gap-2 text-foreground/45">
          <ArrowRight />
          <ArrowRight />
          <ArrowRight />
        </div>

        {/* Right column: updating memory + outcome */}
        <div className="col-span-6 space-y-3">
          <div className="border border-foreground/45 bg-background/70 px-3 py-2 text-center font-terminal text-[10px] tracking-wider text-foreground/90">
            updating memory
          </div>
          <div className="flex justify-center text-foreground/45">
            <ArrowDown />
          </div>
          <div className="border border-border/50 bg-background/60 px-3 py-2 text-center font-terminal text-[10px] tracking-wider text-foreground/90">
            defends the next claim
          </div>
        </div>
      </div>
    </div>
  );
}
function ArrowRight() {
  return (
    <svg width="22" height="10" viewBox="0 0 22 10" aria-hidden>
      <line x1="0" y1="5" x2="18" y2="5" stroke="currentColor" />
      <polygon points="22,5 16,1 16,9" fill="currentColor" />
    </svg>
  );
}
function ArrowDown() {
  return (
    <svg width="10" height="14" viewBox="0 0 10 14" aria-hidden>
      <line x1="5" y1="0" x2="5" y2="10" stroke="currentColor" />
      <polygon points="5,14 1,8 9,8" fill="currentColor" />
    </svg>
  );
}

/* IntegrationCode - Hyperspell's "One Line Integration" visual.
   Mac-style "Connect Your Account" pill at the top, code block below, callout text. */
function IntegrationCode() {
  return (
    <div className="relative grid-paper px-5 py-6 min-h-[280px]">
      <div className="border border-border/50 bg-background/70 px-4 py-2.5 inline-flex items-center gap-2 text-foreground/85 font-terminal text-[11px]">
        <svg width="11" height="11" viewBox="0 0 14 14" aria-hidden>
          <path d="M7 1v8M3 5l4-4 4 4M2 12h10" stroke="currentColor" fill="none" strokeWidth="1" />
        </svg>
        connect your account
      </div>
      <div className="mt-5 border border-border/50 bg-background/65 p-4 font-terminal text-[11px] leading-[1.85]">
        <div className="text-foreground/45">{`<script src="`}<span className="text-[hsl(var(--accent-coral))]">{`https://atlas.sh/v1.js`}</span>{`">`}</div>
        <div>atlas.<span className="text-foreground/85">init</span>{`({`}</div>
        <div>{`  apiKey: `}<span className="text-[hsl(36,42%,76%)]">{`"sk-p19bv02..."`}</span>,</div>
        <div>{`  workspace: `}<span className="text-[hsl(36,42%,76%)]">{`"labs/folding-v3"`}</span>,</div>
        <div>{`  protocol: `}<span className="text-[hsl(36,42%,76%)]">{`"mcp"`}</span></div>
        <div>{`});`}</div>
        <div className="text-foreground/45 mt-1">{`</script>`}</div>
      </div>
      <div className="mt-4 font-terminal text-[10px] leading-[1.7] text-foreground/55 max-w-[26ch]">
        your lab uses atlas to read receipts. you control exactly which artifacts the agents see.
      </div>
    </div>
  );
}

/* SourcesGrid - Hyperspell's "Any Document, Any Source" visual.
   Wide 2x6 icon grid with neutral source icons on a graph-paper background. */
function SourcesGrid() {
  const items = [
    { k: "papers", icon: <PaperIcon /> },
    { k: "arxiv", icon: <PaperIcon /> },
    { k: "github", icon: <GitIcon /> },
    { k: "repos", icon: <RepoIcon /> },
    { k: "runs", icon: <RunIcon /> },
    { k: "datasets", icon: <DataIcon /> },
    { k: "plots", icon: <PlotIcon /> },
    { k: "wandb", icon: <RunIcon /> },
    { k: "notes", icon: <NoteIcon /> },
    { k: "lab.md", icon: <NoteIcon /> },
    { k: "weekly", icon: <CalendarIcon /> },
    { k: "drive", icon: <DataIcon /> },
  ];
  return (
    <VisualShell label="atlas library / sources" pillIcon={<AtlasMark />} stars>
      <div className="grid grid-cols-4 sm:grid-cols-6 gap-2">
        {items.map((s) => (
          <div
            key={s.k}
            className="aspect-square border border-border/45 bg-background/55 backdrop-blur-[2px] flex flex-col items-center justify-center gap-1.5 text-foreground/75 transition-colors duration-500 hover:border-foreground/35"
          >
            {s.icon}
            <span className="font-terminal text-[9px] tabular-nums text-foreground/55">{s.k}</span>
          </div>
        ))}
      </div>
    </VisualShell>
  );
}

/* GraphVisual - Atlas Graph's hero illustration. A node-link research graph:
   circular state-colored nodes, smooth bezier edges, a coral "running" node
   with a soft halo, and a small legend. Drawn precisely, no stock icons. */
function GraphVisual() {
  const C: Record<string, string> = {
    open: "hsl(var(--foreground) / 0.55)",
    running: "hsl(14 75% 62%)",
    supported: "hsl(86 30% 60%)",
    needs: "hsl(28 55% 66%)",
    rejected: "hsl(8 60% 62%)",
  };
  type N = { id: string; x: number; y: number; label: string; state: keyof typeof C };
  const nodes: N[] = [
    { id: "q0", x: 64, y: 96, label: "reranking?", state: "open" },
    { id: "n1", x: 196, y: 66, label: "cross-encoder", state: "running" },
    { id: "n2", x: 186, y: 178, label: "bm25 baseline", state: "supported" },
    { id: "n3", x: 330, y: 110, label: "latency", state: "needs" },
    { id: "n4", x: 320, y: 214, label: "kv-cache", state: "rejected" },
  ];
  const byId = (id: string) => nodes.find((n) => n.id === id)!;
  const edges: Array<[string, string, boolean]> = [
    ["q0", "n1", true],
    ["q0", "n2", false],
    ["n1", "n3", false],
    ["n2", "n4", false],
  ];
  const curve = (a: N, b: N) => {
    const mx = (a.x + b.x) / 2;
    return `M ${a.x} ${a.y} C ${mx} ${a.y}, ${mx} ${b.y}, ${b.x} ${b.y}`;
  };
  return (
    <div className="atmosphere atmosphere-stars w-full h-[440px] flex flex-col">
      <div className="px-5 pt-5 flex items-center justify-between gap-3">
        <VisualPill icon={<AtlasMark />}>atlas graph / sparse-attn</VisualPill>
        <span className="visual-pill-plain">5 nodes</span>
      </div>
      <div className="flex-1 flex items-center justify-center px-5 sm:px-7 pb-3 min-h-0">
        <svg viewBox="0 0 440 300" preserveAspectRatio="xMidYMid meet" className="w-full h-full">
          <defs>
            <pattern id="gdots" width="22" height="22" patternUnits="userSpaceOnUse">
              <circle cx="1" cy="1" r="1" fill="hsl(var(--foreground) / 0.06)" />
            </pattern>
          </defs>
          <rect x="0" y="0" width="440" height="300" fill="url(#gdots)" />

          {edges.map(([a, b, active], i) => {
            const A = byId(a);
            const B = byId(b);
            return (
              <path
                key={i}
                d={curve(A, B)}
                fill="none"
                stroke={active ? C.running : "hsl(var(--foreground) / 0.22)"}
                strokeWidth={active ? 1.4 : 1}
                strokeDasharray={active ? "none" : "3 3"}
                opacity={active ? 0.7 : 1}
              />
            );
          })}

          {nodes.map((n) => {
            const col = C[n.state];
            return (
              <g key={n.id}>
                {n.state === "running" ? (
                  <circle cx={n.x} cy={n.y} r="16" fill="hsl(14 75% 60% / 0.18)" className="animate-pulse" />
                ) : null}
                <circle cx={n.x} cy={n.y} r="10" fill={col} fillOpacity={0.14} stroke={col} strokeOpacity={0.45} />
                <circle cx={n.x} cy={n.y} r="3.5" fill={col} />
                <text
                  x={n.x + 16}
                  y={n.y - 12}
                  fontFamily="JetBrains Mono, monospace"
                  fontSize="10"
                  fill="hsl(var(--foreground) / 0.88)"
                >
                  {n.label}
                </text>
                <text
                  x={n.x + 16}
                  y={n.y + 2}
                  fontFamily="JetBrains Mono, monospace"
                  fontSize="9"
                  fill={col}
                >
                  [{n.state}]
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <div className="px-6 pb-5 flex flex-wrap items-center gap-x-4 gap-y-1.5 font-terminal text-[9px] uppercase tracking-[0.10em] text-foreground/45">
        {([
          ["running", "running"],
          ["supported", "supported"],
          ["needs", "needs evidence"],
          ["rejected", "rejected"],
        ] as Array<[keyof typeof C, string]>).map(([k, label]) => (
          <span key={k} className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full" style={{ background: C[k] }} aria-hidden />
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}

/* SourceIndex - Atlas Library's index, drawn as a measured ledger: source
   class, a coverage bar (private vs public), and a count. No stock icons. */
function SourceIndex() {
  const priv = "hsl(14 75% 58%)";
  const pub = "hsl(86 30% 56%)";
  const rows = [
    { k: "repos", n: "12", pct: 58, scope: "private" as const },
    { k: "papers", n: "248", pct: 96, scope: "public" as const },
    { k: "runs", n: "3.8k", pct: 88, scope: "private" as const },
    { k: "datasets", n: "9", pct: 34, scope: "private" as const },
    { k: "docs", n: "1.2k", pct: 74, scope: "public" as const },
    { k: "notes", n: "64", pct: 26, scope: "private" as const },
  ];
  return (
    <VisualShell label="atlas library / index" pillIcon={<AtlasMark />} stars>
      <div className="flex flex-col gap-2.5">
        {rows.map((r) => (
          <div
            key={r.k}
            className="grid grid-cols-[76px_1fr_44px] items-center gap-3 font-terminal text-[10.5px]"
          >
            <span className="text-foreground/85">{r.k}</span>
            <span className="h-1.5 bg-foreground/10 overflow-hidden">
              <span
                className="block h-full"
                style={{ width: `${r.pct}%`, background: r.scope === "private" ? priv : pub }}
              />
            </span>
            <span className="text-foreground/45 tabular-nums text-right">{r.n}</span>
          </div>
        ))}
        <div className="mt-2 flex items-center gap-4 font-terminal text-[9px] tracking-[0.06em] text-foreground/45">
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2" style={{ background: priv }} aria-hidden />
            private
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2" style={{ background: pub }} aria-hidden />
            public
          </span>
        </div>
      </div>
    </VisualShell>
  );
}

/* AddSourceShot / LibraryListShot - real Atlas Library product screenshots,
   framed on the shared atmosphere backdrop. The modal floats like an overlay;
   the list sits inside a minimal app window. Native aspect ratios preserved. */
function AddSourceShot() {
  return (
    <div className="atmosphere atmosphere-stars w-full h-[440px] flex items-center justify-center p-5 sm:p-6">
      <img
        src={libraryAdd}
        alt="Atlas Library: add a source by URL, local folder, or subscribe to a public index"
        className="block max-h-[400px] w-auto border border-border/50 shadow-[0_30px_80px_-24px_rgba(0,0,0,0.75)] select-none"
        style={{ imageRendering: "auto" }}
        draggable={false}
        decoding="async"
        loading="lazy"
      />
    </div>
  );
}

/* AppWindowShot - a product screenshot inside a minimal app window
   (traffic-light chrome + faux url), floated on the atmosphere backdrop. */
function AppWindowShot({ src, alt, url }: { src: string; alt: string; url: string }) {
  return (
    <div className="atmosphere atmosphere-stars w-full h-[440px] flex items-center justify-center p-5 sm:p-7">
      {/* Capped to the source's native width (1024px) so the screenshot is never
         upscaled, keeping it crisp on high-DPI displays. */}
      <div className="w-full max-w-[560px] mx-auto border border-border/50 bg-background/70 shadow-[0_30px_80px_-24px_rgba(0,0,0,0.75)] overflow-hidden">
        <div className="flex items-center gap-2 px-3.5 h-8 border-b border-border/40 bg-foreground/[0.04]">
          <span className="w-2.5 h-2.5 rounded-full bg-foreground/20" aria-hidden />
          <span className="w-2.5 h-2.5 rounded-full bg-foreground/[0.13]" aria-hidden />
          <span className="w-2.5 h-2.5 rounded-full bg-foreground/[0.09]" aria-hidden />
          <span className="ml-3 font-terminal text-[10px] tracking-[0.08em] text-foreground/45">
            {url}
          </span>
        </div>
        <img
          src={src}
          alt={alt}
          className="block w-full h-auto select-none"
          style={{ imageRendering: "auto" }}
          draggable={false}
          decoding="async"
          loading="lazy"
        />
      </div>
    </div>
  );
}

function LibraryListShot() {
  return (
    <AppWindowShot
      src={libraryList}
      alt="Atlas Library list: indexed papers, repos, docs, datasets, and local folders"
      url="atlas.sh/library"
    />
  );
}

/* ---------------- Atlas Graph card visuals (cohesive set) ---------------- */
/* Shared language: atmosphere backdrop, mono labels, state colors
   (running coral, supported sage, rejected red), a single coral accent. */

const GCOLOR = {
  open: "hsl(var(--foreground) / 0.5)",
  running: "hsl(14 75% 62%)",
  supported: "hsl(86 30% 60%)",
  rejected: "hsl(8 60% 62%)",
} as const;

/* BranchMini - "Branches stay alive": node-link graph with live states. */
function BranchMini() {
  type S = keyof typeof GCOLOR;
  const nodes: Array<{ x: number; y: number; label: string; state: S }> = [
    { x: 56, y: 92, label: "root", state: "open" },
    { x: 210, y: 48, label: "dense+sparse", state: "supported" },
    { x: 200, y: 142, label: "windowed", state: "rejected" },
    { x: 360, y: 56, label: "head-dim", state: "running" },
  ];
  const edges: Array<[number, number, boolean]> = [
    [0, 1, false],
    [0, 2, true],
    [1, 3, false],
  ];
  const curve = (a: { x: number; y: number }, b: { x: number; y: number }) => {
    const mx = (a.x + b.x) / 2;
    return `M ${a.x} ${a.y} C ${mx} ${a.y}, ${mx} ${b.y}, ${b.x} ${b.y}`;
  };
  return (
    <div className="atmosphere atmosphere-stars w-full h-full flex flex-col">
      <div className="px-4 pt-4">
        <VisualPill icon={<AtlasMark />}>map / sparse-attn</VisualPill>
      </div>
      <div className="flex-1 flex items-center justify-center px-3 pb-3 min-h-0">
        <svg viewBox="0 0 420 190" preserveAspectRatio="xMidYMid meet" className="w-full h-full">
          {edges.map(([a, b, dashed], i) => {
            const A = nodes[a];
            const B = nodes[b];
            return (
              <path
                key={i}
                d={curve(A, B)}
                fill="none"
                stroke={dashed ? GCOLOR.rejected : "hsl(var(--foreground) / 0.25)"}
                strokeWidth="1"
                strokeDasharray={dashed ? "3 3" : "none"}
                opacity={dashed ? 0.6 : 1}
              />
            );
          })}
          {nodes.map((n, i) => (
            <g key={i}>
              {n.state === "running" ? (
                <circle cx={n.x} cy={n.y} r="14" fill="hsl(14 75% 60% / 0.18)" className="animate-pulse" />
              ) : null}
              <circle cx={n.x} cy={n.y} r="8" fill={GCOLOR[n.state]} fillOpacity={0.14} stroke={GCOLOR[n.state]} strokeOpacity={0.5} />
              <circle cx={n.x} cy={n.y} r="3" fill={GCOLOR[n.state]} />
              <text x={n.x} y={n.y - 13} textAnchor="middle" fontFamily="JetBrains Mono, monospace" fontSize="9" fill="hsl(var(--foreground) / 0.82)">
                {n.label}
              </text>
            </g>
          ))}
        </svg>
      </div>
    </div>
  );
}

/* BadgeRingCard - ASCII-medal trust card. The medal sits to the left of a
   short title + body. No circular wrapper; the medal IS the visual. */
function BadgeRingCard({
  ring,
  title,
  body,
}: {
  ring: React.ReactNode;
  title: string;
  body: string;
}) {
  return (
    <div className="grain-overlay border border-border/40 bg-background/60 p-7 sm:p-8 flex items-start gap-7 h-full">
      <div className="shrink-0 pt-1">{ring}</div>
      <div>
        <div className={`${H_MED}`}>{title}</div>
        <p className={`mt-3 ${P}`}>{body}</p>
      </div>
    </div>
  );
}

/* TextRing - ASCII medal. Five-line monospace plate with the label centered
   between two padding rows. Reads as `[ CLI ]` stamped on the page;
   same outer width regardless of label length. */
function TextRing({ label }: { label: string }) {
  const W = 7;
  const L = label.length;
  const left = Math.max(0, Math.floor((W - L) / 2));
  const right = Math.max(0, W - L - left);
  const inner = " ".repeat(left) + label + " ".repeat(right);
  const pad = " ".repeat(W);
  return (
    <div className="font-terminal text-[13px] leading-[1.18] whitespace-pre text-foreground/90 select-none">
      <div>╭───────╮</div>
      <div>│{pad}│</div>
      <div>│{inner}│</div>
      <div>│{pad}│</div>
      <div>╰───────╯</div>
    </div>
  );
}

/* SkillsList - packaged agent skills shown as a list with names + descriptions.
   Used in feature card "Built for agents from day one." */
function SkillsList() {
  const skills: Array<[string, string]> = [
    ["atlas-plan", "multi-hop plan mode"],
    ["atlas-auto", "autoresearch loops"],
    ["atlas-gepa", "gepa prompt search"],
    ["atlas-search", "index public + private"],
    ["atlas-reproduce", "clone + replay a claim"],
  ];
  return (
    <VisualShell label="atlas skills:list" pillIcon={<AtlasMark />}>
      <div className="flex flex-col gap-1.5">
        {skills.map(([k, v]) => (
          <div
            key={k}
            className="flex items-center gap-3 border border-border/45 bg-background/60 backdrop-blur-[2px] px-3 py-1.5 font-terminal text-[10px] tabular-nums"
          >
            <span className="text-foreground/90 w-[124px] shrink-0">{k}</span>
            <span className="text-foreground/55 truncate">{v}</span>
          </div>
        ))}
      </div>
    </VisualShell>
  );
}

/* MapTreeBlock - feature card visual for "Shared research graph." */
function MapTreeBlock() {
  return (
    <VisualShell
      label="research map / m_8a2f3c"
      pillIcon={<AtlasMark />}
      stars
    >
      <div className="font-terminal text-[11px] leading-[1.85]">
        <div>
          <span className="text-foreground/45">root</span>
          <span className="text-foreground/40">{"   "}</span>
          <span className="text-foreground/95">does sparse attention preserve recall?</span>
        </div>
        <div>
          <span className="text-foreground/35">├─ </span>
          <span className="text-foreground/45">a</span>
          <span className="text-foreground/40">{"   "}</span>
          <span className="text-foreground/90">swap to local windowed attention</span>
          <span className="text-foreground/40">{"   "}</span>
          <span className="coral-pulse" style={{ color: "hsl(14, 75%, 68%)" }}>
            running
          </span>
        </div>
        <div>
          <span className="text-foreground/35">├─ </span>
          <span className="text-foreground/45">b</span>
          <span className="text-foreground/40">{"   "}</span>
          <span className="text-foreground/90">mix dense + sparse heads</span>
          <span className="text-foreground/40">{"   "}</span>
          <span style={{ color: "hsl(86, 30%, 62%)" }}>supported</span>
        </div>
        <div>
          <span className="text-foreground/35">└─ </span>
          <span className="text-foreground/45">c</span>
          <span className="text-foreground/40">{"   "}</span>
          <span className="text-foreground/90">shrink kv cache, full attention</span>
          <span className="text-foreground/40">{"   "}</span>
          <span style={{ color: "hsl(8, 55%, 65%)" }}>rejected</span>
        </div>
      </div>
    </VisualShell>
  );
}

/* EvidenceBlock - feature card visual for "Evidence as a first-class object." */
function EvidenceBlock() {
  return (
    <VisualShell label="atlas evidence:add" pillIcon={<AtlasMark />} stars>
      <div className="font-terminal text-[11px] leading-[1.7]">
        <div>
          <span className="text-foreground/40">$ </span>
          <span className="text-foreground/95">atlas evidence:add </span>
          <span className="text-foreground/55">\</span>
        </div>
        <div className="pl-4">
          <span className="text-foreground/55">--node-id </span>
          <span className="text-foreground/85">node_42</span>
          <span className="text-foreground/55"> \</span>
        </div>
        <div className="pl-4">
          <span className="text-foreground/55">--items </span>
          <span style={{ color: "hsl(36, 42%, 76%)" }}>@loss_curves.json</span>
        </div>
        <div className="text-foreground/55">
          attached 4 artifacts to <span className="text-foreground/85">node_42</span>
        </div>
        <div className="h-1" />
        <div>
          <span className="text-foreground/40">$ </span>
          <span className="text-foreground/95">atlas evidence:note </span>
          <span className="text-foreground/55">\</span>
        </div>
        <div className="pl-4">
          <span className="text-foreground/55">--node-id </span>
          <span className="text-foreground/85">node_42</span>
          <span className="text-foreground/55"> \</span>
        </div>
        <div className="pl-4">
          <span className="text-foreground/55">--note </span>
          <span style={{ color: "hsl(36, 42%, 76%)" }}>"loss plateau at step 14k"</span>
        </div>
      </div>
    </VisualShell>
  );
}

/* ReproduceBlock - feature card visual for "Reproducible by default." */
function ReproduceBlock() {
  return (
    <VisualShell
      label="atlas map:reproduce"
      pillIcon={<AtlasMark />}
      stars
    >
      <div className="font-terminal text-[11px] leading-[1.7]">
        <div>
          <span className="text-foreground/40">$ </span>
          <span className="text-foreground/95">atlas map:clone </span>
          <span className="text-foreground/55">\</span>
        </div>
        <div className="pl-4">
          <span className="text-foreground/55">--map-id </span>
          <span style={{ color: "hsl(36, 42%, 76%)" }}>atlas/iclr/2026/sparse-attn</span>
        </div>
        <div className="h-1" />
        <div>
          <span className="text-foreground/40">$ </span>
          <span className="text-foreground/95">atlas map:reproduce </span>
          <span className="text-foreground/55">\</span>
        </div>
        <div className="pl-4">
          <span className="text-foreground/55">--node-id </span>
          <span className="text-foreground/85">node_42</span>
        </div>
        <div className="text-foreground/55">running 4 nodes...</div>
        <div>
          <span style={{ color: "hsl(86, 30%, 62%)" }}>3 passed</span>
          <span className="text-foreground/55">{"   "}</span>
          <span className="coral-pulse" style={{ color: "hsl(14, 75%, 68%)" }}>
            1 diverged
          </span>
          <span className="text-foreground/55">{"   "}see </span>
          <span className="text-foreground/85">report.json</span>
        </div>
      </div>
    </VisualShell>
  );
}

/* EvidenceClaim - claim card with a separated runs / artifacts block. */
function EvidenceClaim() {
  return (
    <VisualShell label="claim / n_4d8e1b2" pillIcon={<AtlasMark />}>
      <div className="flex flex-col gap-3">
        <div className="border border-border/45 bg-background/65 backdrop-blur-[2px] px-3 py-2.5">
          <div className="flex items-center justify-between text-[10px] font-terminal">
            <span className="text-foreground/45 tabular-nums">n_4d8e1b2  claim</span>
            <span className={stateClass.supported}>[supported]</span>
          </div>
          <div className="mt-1 text-[12px] text-foreground/90">cross-encoder helps short queries</div>
        </div>
        <div className="border border-border/45 bg-background/55 backdrop-blur-[2px] px-3 py-2.5 font-terminal text-[10px] leading-[1.85]">
          <div className="text-foreground/45 mb-1">evidence</div>
          <div className="flex justify-between text-foreground/80">
            <span>run_a93f.json</span>
            <span className={stateClass.supported}>passed</span>
          </div>
          <div className="flex justify-between text-foreground/80">
            <span>plot_2c1.png</span>
            <span className={stateClass.supported}>ok</span>
          </div>
          <div className="flex justify-between text-foreground/80">
            <span>cordy@v0.6.2</span>
            <span className={stateClass.supported}>linked</span>
          </div>
        </div>
      </div>
    </VisualShell>
  );
}

/* LibrarySearch - ranked retrieval mockup. A query bar with a live caret,
   then results carrying a snippet, source, and a relevance bar. */
function LibrarySearch() {
  const results = [
    { src: "arxiv:2402.18668", snip: "mamba: linear-time", score: 0.92 },
    { src: "repos/labs/cordy", snip: "bench/short.py:42", score: 0.88 },
    { src: "arxiv:2024.123", snip: "reranker-survey.pdf", score: 0.81 },
    { src: "notes/lab-q4.md", snip: "section: scaling", score: 0.77 },
  ];
  return (
    <VisualShell label="atlas library / search" pillIcon={<AtlasMark />} stars>
      <div className="flex items-center gap-2 border border-border/55 bg-background/55 backdrop-blur-[2px] px-3 h-9 font-terminal text-[11px] mb-3">
        <span className="text-foreground/40">$</span>
        <span className="text-foreground/85">state space scaling</span>
        <span className="terminal-cursor" aria-hidden />
      </div>
      <div className="flex flex-col gap-1.5">
        {results.map((r) => (
          <div
            key={r.src}
            className="border border-border/45 bg-background/55 backdrop-blur-[2px] px-3 py-2 font-terminal text-[10px]"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-foreground/85 truncate">{r.snip}</span>
              <span className="text-foreground/45 tabular-nums shrink-0">{r.score.toFixed(2)}</span>
            </div>
            <div className="mt-1.5 flex items-center gap-2">
              <span className="text-foreground/45 truncate shrink-0 min-w-[96px]">{r.src}</span>
              <span className="relative flex-1 h-px bg-foreground/10 overflow-hidden">
                <span
                  className="absolute inset-y-0 left-0"
                  style={{ width: `${r.score * 100}%`, background: "hsl(86 30% 56% / 0.65)" }}
                />
              </span>
            </div>
          </div>
        ))}
      </div>
    </VisualShell>
  );
}

/* PortPaperBlock - visual for "reproduce a paper" card. */
function PortPaperBlock() {
  return (
    <VisualShell
      label="atlas-reproduce arxiv:2402.18668"
      pillIcon={<AtlasMark />}
      stars
    >
      <div className="flex flex-col gap-1.5">
        {[
          ["claim_01", "linear-time scaling", "open"],
          ["claim_02", "matches transformer at 1.4B", "running"],
          ["claim_03", "gating retains state", "supported"],
          ["claim_04 (missing ablation)", "head dim sweep", "needs-evidence"],
        ].map(([k, v, state]) => (
          <div
            key={k}
            className="flex items-center gap-2 border border-border/45 bg-background/60 backdrop-blur-[2px] px-3 py-1.5 font-terminal text-[10px]"
          >
            <span className="text-foreground/45 tabular-nums shrink-0 min-w-[124px]">{k}</span>
            <span className="text-foreground/85 truncate flex-1">{v}</span>
            <span className={`tabular-nums shrink-0 ${stateClass[state as State]}`}>[{state}]</span>
          </div>
        ))}
      </div>
    </VisualShell>
  );
}

/* DelegationVisual - Live activity feed of agents writing into Atlas. Height
   is locked to the neighbor dither box (440px) so the row reads as a
   balanced pair; rows distribute evenly to fill the card. */
function DelegationVisual() {
  type Row = { project: string; action: string; status: "ok" | "warn" | "neutral"; ago: string };
  const rows: Row[] = [
    { project: "folding-v3", action: "agent advanced 8 nodes", status: "ok", ago: "2m" },
    { project: "sparse-attn", action: "reproduced arxiv:2402.18", status: "ok", ago: "5m" },
    { project: "rlhf-v2", action: "4 branches forked", status: "neutral", ago: "7m" },
    { project: "safety-eval", action: "12 evidence attached", status: "ok", ago: "14m" },
    { project: "scaling-laws", action: "autoresearch 1h12m run", status: "warn", ago: "22m" },
    { project: "cordy", action: "claim_07 supported", status: "ok", ago: "31m" },
    { project: "moe-routing", action: "ablation sweep done", status: "neutral", ago: "44m" },
  ];
  const statusColor: Record<Row["status"], string> = {
    ok: "hsl(86, 30%, 62%)",
    warn: "hsl(28, 55%, 68%)",
    neutral: "hsl(var(--foreground) / 0.45)",
  };

  return (
    <div className="atmosphere atmosphere-stars w-full h-[440px] flex flex-col">
      <div className="px-5 pt-5 flex items-center justify-between gap-3">
        <VisualPill icon={<AtlasMark />}>atlas auto:tail --lab=*</VisualPill>
        <div
          className="visual-pill"
          style={{ borderColor: "hsl(14 70% 60% / 0.55)", color: "hsl(14 75% 70%)" }}
        >
          <span className="visual-pill-dot" aria-hidden />
          live
        </div>
      </div>

      <div className="flex-1 flex flex-col px-5 sm:px-6 pb-5 pt-4 min-h-0">
        {/* Column header */}
        <div className="flex items-center gap-3 font-terminal text-[10px] uppercase tracking-[0.10em] text-foreground/45 pb-2 border-b border-border/40">
          <span className="w-1.5 shrink-0" aria-hidden />
          <span className="w-[112px] shrink-0">project</span>
          <span className="flex-1">event</span>
          <span className="w-[56px] shrink-0 text-right">ago</span>
        </div>

        {/* Activity rows - flex-1 + justify-between distributes them evenly so
            the feed reads as filling the card rather than floating mid-air. */}
        <div className="flex-1 flex flex-col justify-between py-1.5">
          {rows.map((r) => (
            <div
              key={r.project}
              className="flex items-center gap-3 font-terminal text-[11.5px] leading-tight py-1"
            >
              <span
                className="shrink-0 w-1.5 h-1.5 rounded-full"
                style={{ background: statusColor[r.status] }}
                aria-hidden
              />
              <span className="w-[112px] shrink-0 text-foreground/85 truncate">
                {r.project}
              </span>
              <span className="flex-1 text-foreground/90 truncate">{r.action}</span>
              <span className="w-[56px] shrink-0 text-right tabular-nums text-foreground/45">
                {r.ago}
              </span>
            </div>
          ))}
        </div>

        {/* Summary footer keeps the bottom edge grounded with a count line. */}
        <div className="flex items-center justify-between pt-3 border-t border-border/40 font-terminal text-[10px] tracking-[0.10em] uppercase">
          <span className="text-foreground/55">7 projects / 41 nodes today</span>
          <span className="text-foreground/45">tail --follow</span>
        </div>
      </div>
    </div>
  );
}

/* ----------------------------- Mac Terminal ----------------------------- */

const TC = {
  prompt: "text-foreground/40",
  cmd: "text-foreground",
  sub: "text-[hsl(38,55%,72%)]",
  flag: "text-foreground/55",
  str: "text-[hsl(36,42%,76%)]",
  id: "text-[hsl(38,58%,72%)]",
  ok: "text-[hsl(86,30%,62%)]",
  warn: "text-[hsl(28,55%,68%)]",
  prog: "text-foreground/60",
  state: "text-foreground/55",
  dim: "text-foreground/40",
  tree: "text-foreground/35",
};

function MacTerminal() {
  const PROMPT = "ishaan@labs sparse-attn %";
  /* Tag - small left-margin label that names the autoresearch phase.
     Matches Atlas's stateful color scheme without cluttering each line. */
  const Tag = ({ kind }: { kind: "propose" | "search" | "branch" | "run" | "evidence" | "reproduce" | "summary" }) => {
    const colors: Record<string, string> = {
      propose: "text-[hsl(38,55%,72%)]",
      search: "text-foreground/65",
      branch: "text-[hsl(38,58%,72%)]",
      run: "text-foreground/65",
      evidence: "text-[hsl(86,30%,62%)]",
      reproduce: "text-[hsl(86,30%,62%)]",
      summary: "text-foreground/85",
    };
    return <span className={`${colors[kind]} w-[88px] inline-block`}>[{kind}]</span>;
  };
  return (
    <div className="font-terminal rounded-md overflow-hidden border border-black/50 shadow-[0_30px_80px_-20px_rgba(0,0,0,0.6)] bg-[hsl(28,14%,7%)]">
      <div className="relative flex items-center px-3.5 py-2 bg-gradient-to-b from-[hsl(30,8%,18%)] to-[hsl(30,8%,13%)] border-b border-black/60">
        <div className="flex gap-2">
          <span className="h-3 w-3 rounded-full bg-[#ff5f57] ring-1 ring-inset ring-black/30 shadow-[inset_0_-1px_0_rgba(0,0,0,0.2)]" />
          <span className="h-3 w-3 rounded-full bg-[#febc2e] ring-1 ring-inset ring-black/30 shadow-[inset_0_-1px_0_rgba(0,0,0,0.2)]" />
          <span className="h-3 w-3 rounded-full bg-[#28c840] ring-1 ring-inset ring-black/30 shadow-[inset_0_-1px_0_rgba(0,0,0,0.2)]" />
        </div>
        <div className="absolute left-1/2 -translate-x-1/2 text-[13px] text-foreground/65">
          ishaan / atlas / sparse-attn
        </div>
      </div>

      <div className="px-5 sm:px-6 py-5 text-[13px] leading-[1.75] whitespace-pre overflow-x-auto bg-[hsl(28,14%,8%)]">
        {/* User kicks off an autoresearch run. */}
        <div>
          <span className={TC.prompt}>{PROMPT}</span>{" "}
          <span className={TC.cmd}>atlas</span>{" "}
          <span className={TC.sub}>auto</span>{" "}
          <span className={TC.flag}>--node</span>{" "}
          <span className={TC.id}>n_4d8e</span>{" "}
          <span className={TC.flag}>--budget</span>{" "}
          <span className={TC.str}>4h</span>{" "}
          <span className={TC.flag}>--skills</span>{" "}
          <span className={TC.str}>atlas-search,atlas-reproduce</span>
        </div>
        <div className="text-foreground/55">  agent: claude-3.7-opus  scope: this branch + 1 hop  taste-checks: every 3 nodes</div>

        <div className="h-3" />

        {/* Agent proposes, searches, runs, attaches evidence, branches, and reproduces. */}
        <div><Tag kind="propose" /><span className={TC.dim}> gating retains state under sparse heads</span></div>
        <div><Tag kind="search" /><span className={TC.dim}>  </span><span className={TC.dim}>14 sources retrieved across 3 indices</span></div>
        <div><Tag kind="run" /><span className={TC.dim}>     launching </span><span className={TC.id}>run_a93f</span><span className={TC.dim}> on h100</span></div>
        <div><Tag kind="run" /><span className={TC.dim}>     loss converged at step 12k                </span><span className={TC.ok}>passed</span></div>
        <div><Tag kind="evidence" /><span className={TC.dim}>attached </span><span className={TC.id}>run_a93f.json</span><span className={TC.dim}>, </span><span className={TC.id}>plot_2c1.png</span></div>
        <div><Tag kind="branch" /><span className={TC.dim}>  forked </span><span className={TC.id}>b_7a2f</span><span className={TC.dim}> from </span><span className={TC.id}>n_4d8e</span></div>

        <div className="h-3" />

        {/* Reproduce a prior paper's claim against the same map. */}
        <div><Tag kind="reproduce" /><span className={TC.dim}>cloning </span><span className={TC.id}>arxiv:2402.18668</span><span className={TC.dim}>::claim_03</span></div>
        <div><span className={TC.dim}>           3 of 4 nodes reproduced              </span><span className={TC.warn}>1 diverged</span></div>

        <div className="h-3" />

        <div><Tag kind="summary" /><span className={TC.dim}> advanced 8 nodes in 1h12m                  </span><span className={TC.warn}>2 needs-review</span></div>
        <div><span className={TC.dim}>           waiting for taste check at </span><span className={TC.id}>b_7a2f.q3</span></div>

        <div className="h-3" />

        <div>
          <span className={TC.prompt}>{PROMPT}</span>
          <span className="terminal-cursor" aria-hidden />
        </div>
      </div>
    </div>
  );
}

/* --------------------------------- Page --------------------------------- */

/* StepTerminal - compact terminal snippet used inside the How It Works
   timeline cards. Same visual vocabulary as the autoresearch terminal:
   `$ ` prompt, command, flag-style args, line continuations. */
function StepTerminal({ lines, label }: { lines: Array<React.ReactNode>; label?: string }) {
  return (
    <VisualShell label={label} pillIcon={<AtlasMark />}>
      <div className="font-terminal text-[10.5px] leading-[1.7] flex flex-col gap-1">
        {lines.map((ln, i) => (
          <div key={i}>{ln}</div>
        ))}
      </div>
    </VisualShell>
  );
}

/* Step-terminal token colors used by the How It Works STEPS array.
   SystemDiagram declares its own block-scoped `const C` with a different
   shape; that local declaration shadows this file-level one within the
   function body, so both work side by side. */
const STEP_C = {
  prompt: "text-foreground/40",
  cmd: "text-foreground/95",
  flag: "text-foreground/55",
  str: "text-[hsl(36,42%,76%)]",
  id: "text-[hsl(38,58%,72%)]",
  ok: "text-[hsl(86,30%,62%)]",
  dim: "text-foreground/55",
} as const;

/* STEPS - declarative source of truth for the timeline. Each step renders
   into one card with step number, title, terminal mock, and 1-line body. */
const STEPS: Array<{
  n: string;
  title: string;
  body: string;
  visual: React.ReactNode;
}> = [
  {
    n: "01",
    title: "Install.",
    body: "Add Atlas skills to Claude Code, Codex, Cursor, or your own harness.",
    visual: (
      <StepTerminal
        label="atlas login"
        lines={[
          <>
            <span className={STEP_C.prompt}>$ </span>
            <span className={STEP_C.cmd}>atlas login</span>
          </>,
          <>
            <span className={STEP_C.dim}>+ logged in as </span>
            <span className={STEP_C.id}>ishaan@labs</span>
          </>,
          <span className="block h-1" />,
          <>
            <span className={STEP_C.prompt}>$ </span>
            <span className={STEP_C.cmd}>atlas skills:install </span>
            <span className={STEP_C.flag}>\</span>
          </>,
          <>
            <span className="pl-4">
              <span className={STEP_C.flag}>--target </span>
              <span className={STEP_C.str}>claude-code</span>
            </span>
          </>,
          <>
            <span className={STEP_C.dim}>+ installed </span>
            <span className={STEP_C.ok}>5 skills</span>
          </>,
        ]}
      />
    ),
  },
  {
    n: "02",
    title: "Map.",
    body: "Start with a question. Branch hypotheses, runs, objections, and decisions.",
    visual: (
      <StepTerminal
        label="atlas nodes:create"
        lines={[
          <>
            <span className={STEP_C.prompt}>$ </span>
            <span className={STEP_C.cmd}>atlas nodes:create </span>
            <span className={STEP_C.flag}>\</span>
          </>,
          <span className="pl-4">
            <span className={STEP_C.flag}>--payload </span>
            <span className={STEP_C.str}>@root.json</span>
          </span>,
          <>
            <span className={STEP_C.dim}>+ created </span>
            <span className={STEP_C.id}>node_01</span>
          </>,
          <span className="block h-1" />,
          <>
            <span className={STEP_C.prompt}>$ </span>
            <span className={STEP_C.cmd}>atlas nodes:branch </span>
            <span className={STEP_C.flag}>\</span>
          </>,
          <span className="pl-4">
            <span className={STEP_C.flag}>--title </span>
            <span className={STEP_C.str}>"try reranker"</span>
          </span>,
          <>
            <span className={STEP_C.dim}>+ created </span>
            <span className={STEP_C.id}>node_02</span>
          </>,
        ]}
      />
    ),
  },
  {
    n: "03",
    title: "Run.",
    body: "Agents search indexed sources, run experiments, attach evidence, and keep branching.",
    visual: (
      <StepTerminal
        label="atlas auto --budget 4h"
        lines={[
          <>
            <span className={STEP_C.prompt}>$ </span>
            <span className={STEP_C.cmd}>atlas auto </span>
            <span className={STEP_C.flag}>\</span>
          </>,
          <span className="pl-4">
            <span className={STEP_C.flag}>--node </span>
            <span className={STEP_C.id}>n_4d8e</span>
            <span className={STEP_C.flag}> \</span>
          </span>,
          <span className="pl-4">
            <span className={STEP_C.flag}>--budget </span>
            <span className={STEP_C.str}>4h</span>
          </span>,
          <span className="block h-1" />,
          <span className={STEP_C.dim}>[propose] gating retains state...</span>,
          <span className={STEP_C.dim}>[run]     loss converged at 12k</span>,
          <>
            <span className={STEP_C.dim}>[summary] </span>
            <span className={STEP_C.ok}>+8 nodes in 1h12m</span>
          </>,
        ]}
      />
    ),
  },
  {
    n: "04",
    title: "Export.",
    body: "Generate paper drafts, evidence packs, or reproduction maps from the same graph.",
    visual: (
      <StepTerminal
        label="atlas paper:export"
        lines={[
          <>
            <span className={STEP_C.prompt}>$ </span>
            <span className={STEP_C.cmd}>atlas paper:export </span>
            <span className={STEP_C.flag}>\</span>
          </>,
          <span className="pl-4">
            <span className={STEP_C.flag}>--map-id </span>
            <span className={STEP_C.str}>iclr/2026/sparse-attn</span>
          </span>,
          <span className="pl-4">
            <span className={STEP_C.flag}>--format </span>
            <span className={STEP_C.str}>latex</span>
          </span>,
          <span className="block h-1" />,
          <>
            <span className={STEP_C.dim}>+ wrote </span>
            <span className={STEP_C.id}>paper.tex</span>
            <span className={STEP_C.dim}> (12k tokens)</span>
          </>,
          <>
            <span className={STEP_C.dim}>+ </span>
            <span className={STEP_C.ok}>4 figures, 14 citations</span>
          </>,
        ]}
      />
    ),
  },
];

/* FaqItem - single collapsible row inside the FAQ list. Animates the answer
   open/close via a CSS grid-rows trick (height: 0 ↔ auto) instead of a
   hardcoded max-height, so any answer length animates correctly. */
function FaqItem({
  q,
  a,
  isOpen,
  onToggle,
}: {
  q: string;
  a: string;
  isOpen: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="border-t border-border/40 first:border-t-0">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={isOpen}
        className="w-full text-left py-7 flex items-center gap-5 group cursor-pointer"
      >
        <div className="flex-1">
          <div
            className={`${H_MED} transition-colors duration-300 ${
              isOpen ? "text-foreground" : "text-foreground/80 group-hover:text-foreground"
            }`}
          >
            {q}
          </div>
        </div>
        <span
          className={`text-[hsl(var(--accent-coral))] shrink-0 transition-transform duration-300 ${
            isOpen ? "rotate-180" : ""
          }`}
          aria-hidden
        >
          <svg width="14" height="8" viewBox="0 0 14 8" fill="none">
            <polyline
              points="1,1 7,7 13,1"
              stroke="currentColor"
              strokeWidth="1.5"
            />
          </svg>
        </span>
      </button>
      <div
        className={`grid transition-[grid-template-rows] duration-300 ease-out ${
          isOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
        }`}
      >
        <div className="overflow-hidden">
          <p className={`pr-12 pb-7 max-w-[58ch] ${P}`}>{a}</p>
        </div>
      </div>
    </div>
  );
}

/* FaqList - exclusive accordion. Only one item is open at a time so the
   reader's eye stays anchored on a single answer. First item starts open. */
function FaqList({
  items,
}: {
  items: Array<{ q: string; a: string }>;
}) {
  const [openIdx, setOpenIdx] = useState<number | null>(0);
  return (
    <div>
      {items.map((item, i) => (
        <FaqItem
          key={item.q}
          q={item.q}
          a={item.a}
          isOpen={openIdx === i}
          onToggle={() => setOpenIdx(openIdx === i ? null : i)}
        />
      ))}
    </div>
  );
}

export default function Landing() {
  return (
    <div
      id="top"
      className="min-h-screen bg-background text-foreground antialiased selection:bg-primary/30 selection:text-foreground"
    >
      {/* ============================== HERO ============================== */}
      <section className="relative h-screen min-h-[680px] w-full bg-background overflow-hidden">
        <img
          src={heroMap}
          alt="A drawn cartographic map of an unknown territory"
          className="absolute top-0 left-0 w-full h-auto select-none"
          style={{
            imageRendering: "auto",
            maskImage: "linear-gradient(to bottom, black 62%, transparent 99%)",
            WebkitMaskImage: "linear-gradient(to bottom, black 62%, transparent 99%)",
          }}
          draggable={false}
        />

        <div
          className="pointer-events-none absolute inset-x-0 bottom-0 z-[5]"
          style={{
            height: "68%",
            background:
              "linear-gradient(to top, hsl(var(--background)) 0%, hsl(var(--background) / 0.96) 20%, hsl(var(--background) / 0.72) 44%, hsl(var(--background) / 0.35) 70%, hsl(var(--background) / 0) 100%)",
          }}
        />

        {/* One padded container holds both the wordmark and the copy, so the
            left gap (border -> headline) matches the right gap (wordmark ->
            border). */}
        <div className="absolute inset-0 z-10 mx-auto flex h-full max-w-[1400px] flex-col px-6 sm:px-10">
          <div className="hero-text rise self-end text-right mt-[10vh]" style={{ animationDelay: "120ms" }}>
            <div className="text-[clamp(56px,8vw,128px)] leading-[0.9] tracking-[-0.04em]">atlas</div>
            <a
              href="https://syntheticsciences.ai"
              target="_blank"
              rel="noopener noreferrer"
              className="mt-1 inline-block text-[clamp(13px,1.2vw,17px)] tracking-[0.03em] text-foreground/55 transition-colors hover:text-foreground/85"
            >
              by Synthetic Sciences
            </a>
          </div>

          <div className="hero-text mt-auto mb-[7vh] max-w-[800px]">
            <div className="rise" style={{ animationDelay: "260ms" }}>
              <h1 className="text-balance text-[clamp(34px,4.6vw,62px)] leading-[1.04] tracking-[-0.024em] text-foreground">
                Infrastructure for autonomous, open science.
              </h1>
            </div>
            <div className="rise" style={{ animationDelay: "420ms" }}>
              <p className={`mt-6 max-w-[52ch] ${P_BIG} text-foreground/80`}>
                Atlas is the record your agents write to and the library they
                search.
              </p>
            </div>
            <div className="rise mt-9 flex flex-wrap items-center gap-3 [text-shadow:none]" style={{ animationDelay: "580ms" }}>
              <Cta href="https://app.syntheticsciences.ai">Get started</Cta>
              <Cta href="https://docs.syntheticsciences.ai" variant="ghost" arrow={false}>
                Read the docs
              </Cta>
              <InstallChip className="hidden lg:inline-flex ml-2" />
            </div>
          </div>
        </div>
      </section>

      {/* =========================== TRUST STRIP (provided logos) =================== */}
      <section className="relative w-full overflow-hidden border-t border-border/40 py-14">
        <div className="relative z-10">
          <div className="mb-9 text-center text-[14px] tracking-[0.04em] text-foreground/55">
            Used by researchers at
          </div>
          <div className="marquee-mask overflow-hidden">
            <div className="marquee-track">
              {[0, 1].map((group) => (
                <div className="marquee-group" key={group} aria-hidden={group === 1}>
                  {LOGOS.map((logo) => (
                    <div key={`${logo.id}-${group}`} className="flex items-center gap-14">
                      <img
                        src={logo.src}
                        alt={logo.alt}
                        title={logo.alt}
                        className="logo-wall-img"
                        data-logo={logo.id}
                        draggable={false}
                      />
                      <span className="trust-dot" aria-hidden />
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* =================================================================== */}
      {/* PRODUCTS - Graph, then Library. Each gets two                        */}
      {/* sections: a dithered statement + a clean detail. No listing section,  */}
      {/* no product count; the suite is presented as it grows.                */}
      {/* =================================================================== */}

      {/* ---------- ATLAS GRAPH / statement (dither-warm + graph) ---------- */}
      <section id="graph" className="relative w-full overflow-hidden border-t border-border/40">
        <div className="relative z-10 mx-auto max-w-[1400px] w-full px-6 sm:px-10 py-24 sm:py-32">
          <div className="grid grid-cols-12 gap-8 lg:gap-12 items-stretch">
            <Reveal className="col-span-12 lg:col-span-6">
              <div className="dither-warm border border-border/40 p-8 sm:p-12 min-h-[440px] h-full flex flex-col justify-center">
                <div className="dither-content">
                  <Eyebrow tone="bright" className="mb-6">Atlas Graph</Eyebrow>
                  <h2 className={`text-balance ${H_HUGE} text-foreground`}>
                    The PDF is not enough.
                  </h2>
                  <p className={`mt-7 max-w-[38ch] ${P_BIG} text-foreground/85`}>
                    An agent runs more experiments in an afternoon than used to
                    fill a week. Atlas Graph keeps every run, branch, and result
                    in one place, written as the work happens.
                  </p>
                </div>
              </div>
            </Reveal>
            <Reveal delay={150} className="col-span-12 lg:col-span-6 self-center">
              <div className="border border-border/40 overflow-hidden h-[440px]">
                <Plate>
                  <GraphHero />
                </Plate>
              </div>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ---------- ATLAS GRAPH / detail (clean + primitives 2x2) ---------- */}
      <Section seed={3} className="py-24 sm:py-32">
        <div className="max-w-[820px]">
          <Reveal>
            <h2 className={`text-balance ${H_BIG}`}>
              Made to be forked and rerun.
            </h2>
          </Reveal>
          <Reveal delay={180}>
            <p className={`mt-6 max-w-[48ch] ${P_BIG}`}>
              Every step happens on the same shared record.
            </p>
          </Reveal>
        </div>

        <div className="mt-16 grid grid-cols-12 gap-px bg-border/40 border border-border/40">
          {[
            {
              visual: <Plate className="!p-3"><ForkVisual /></Plate>,
              title: "GitHub for research.",
              body: "Browse public graphs, fork a paper, and push past where it stalled. Or share your own; coauthors and agents pick up where you left off.",
            },
            {
              visual: <Plate className="!p-3"><ReproduceVisual /></Plate>,
              title: "Reproducible by default.",
              body: "Artifacts attach as the work happens: configs, logs, plots, diffs, checkpoints. Clone the graph and rerun the claims.",
            },
            {
              visual: <Plate className="!p-3"><AutoresearchVisual /></Plate>,
              title: "Autoresearch at scale.",
              body: "Atlas CLI and skills make a project operable by your agent: multi-hop plan mode, autoresearch, GEPA, and more.",
            },
          ].map((f, i) => (
            <Reveal
              key={f.title}
              delay={i * 90}
              className="col-span-12 md:col-span-4 bg-background"
            >
              <div className="group h-full flex flex-col transition-colors duration-500 hover:bg-foreground/[0.02]">
                <div className="bg-background/55 border-b border-border/40 px-6 sm:px-8 pt-6 pb-4">
                  <div className="border border-border/40 h-[240px] overflow-hidden transition-all duration-500 group-hover:border-foreground/35 group-hover:-translate-y-0.5">
                    {f.visual}
                  </div>
                </div>
                <div className="p-7 sm:p-8 flex-1">
                  <h3 className={`${H_MED}`}>{f.title}</h3>
                  <p className={`mt-3.5 max-w-[42ch] ${P}`}>{f.body}</p>
                </div>
              </div>
            </Reveal>
          ))}
        </div>
      </Section>

      {/* ---------- ATLAS LIBRARY / statement (search + dither-purple) ----- */}
      <section id="library" className="relative w-full overflow-hidden border-t border-border/40">
        <div className="relative z-10 mx-auto max-w-[1400px] w-full px-6 sm:px-10 py-24 sm:py-32">
          <div className="grid grid-cols-12 gap-8 lg:gap-12 items-stretch">
            <Reveal className="col-span-12 lg:col-span-6 self-center order-2 lg:order-1">
              <div className="border border-border/40 overflow-hidden h-[440px]">
                <AddSourceShot />
              </div>
            </Reveal>
            <Reveal delay={150} className="col-span-12 lg:col-span-6 order-1 lg:order-2">
              <div className="dither-purple border border-border/40 p-8 sm:p-12 min-h-[440px] h-full flex flex-col justify-center">
                <div className="dither-content">
                  <Eyebrow tone="bright" className="mb-6">Atlas Library</Eyebrow>
                  <h2 className={`text-balance ${H_HUGE} text-foreground`}>
                    The agent cannot see your work.
                  </h2>
                  <p className={`mt-7 max-w-[38ch] ${P_BIG} text-foreground/85`}>
                    So it guesses from year-old training data. Atlas Library lets
                    it search your repos, papers, datasets, and runs first, and
                    answer from those.
                  </p>
                </div>
              </div>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ---------- ATLAS LIBRARY / detail (clean + source index) --------- */}
      <Section seed={4} className="py-24 sm:py-32">
        <div className="grid grid-cols-12 gap-8 lg:gap-12 items-stretch">
          <Reveal className="col-span-12 lg:col-span-5 self-center">
            <h2 className={`text-balance ${H_BIG}`}>
              Private and public sources.
            </h2>
            <p className={`mt-6 max-w-[40ch] ${P_BIG}`}>
              Repos, papers, datasets, runs, and notes, searched as one corpus.
              You set what the agent can see.
            </p>
            <div className="mt-7 flex flex-wrap gap-2 text-[13px]">
              {["Bring your own keys", "Private by default"].map((t) => (
                <span
                  key={t}
                  className="inline-flex items-center px-3 py-1.5 border border-border/60 bg-background/40 backdrop-blur-[2px] text-foreground/70"
                >
                  {t}
                </span>
              ))}
            </div>
          </Reveal>
          <Reveal delay={150} className="col-span-12 lg:col-span-7 self-center">
            <div className="border border-border/40 overflow-hidden h-[440px]">
              <LibraryListShot />
            </div>
          </Reveal>
        </div>
      </Section>

      {/* ===================== MID-CTA (red dither sunset) ==================== */}
      {/* Synthesis pivot after the product sections: names the payoff for the
          people who run the lab, then leads into the FAQ + final CTA. */}
      <section className="relative w-full overflow-hidden border-t border-border/40 dither-red">
        <div className="dither-content mx-auto max-w-[1400px] w-full px-6 sm:px-10 py-28 sm:py-36">
          <div className="max-w-[900px] mx-auto text-center">
            <Reveal>
              <Eyebrow tone="bright" className="justify-center mb-6">For labs and PIs</Eyebrow>
              <h2 className={`text-balance ${H_HUGE} text-foreground`}>
                Rigor without more process.
              </h2>
            </Reveal>
            <Reveal delay={200}>
              <p className={`mt-7 mx-auto max-w-[44ch] ${P_BIG} text-foreground/85`}>
                The researcher works as usual. Atlas captures the structure
                underneath, so the project is reproducible and shareable by
                default.
              </p>
            </Reveal>
          </div>
        </div>
      </section>

      {/* =================== FAQ (left/right with chevrons) ================= */}
      <Section seed={7} className="py-24 sm:py-32" id="faq">
        <div className="grid grid-cols-12 gap-10 lg:gap-16">
          {/* Left: heading column */}
          <div className="col-span-12 lg:col-span-5 lg:sticky lg:top-28 self-start">
            <Reveal>
              <h2 className={`text-balance ${H_BIG}`}>
                Frequently asked questions.
              </h2>
              <p className={`mt-6 max-w-[36ch] ${P_BIG}`}>
                Everything else lives in the docs.
              </p>
            </Reveal>
          </div>

          {/* Right: collapsible accordion. First item starts open;
              clicking another swaps focus to that one. */}
          <div className="col-span-12 lg:col-span-7">
            <FaqList
              items={[
                {
                  q: "What is Atlas?",
                  a: "Infrastructure for research agents. Atlas Graph keeps the record of the work, and Atlas Library gives agents your sources.",
                },
                {
                  q: "Which products are available?",
                  a: "Atlas Graph is available now. Atlas Library is rolling out.",
                },
                {
                  q: "How does it reduce hallucination?",
                  a: "Agents query indexed project sources before they act: repos, papers, datasets, notes, runs, prior attempts, plus public docs. Claims cite the material they depend on.",
                },
                {
                  q: "How does this help coauthors?",
                  a: "Every branch, failure, and result sits in one place your coauthors can open, instead of scattered across Slack and notebooks.",
                },
                {
                  q: "How does Atlas handle reproducibility?",
                  a: "Configs, logs, plots, notebooks, diffs, and checkpoints attach as the work happens. A forked copy can be rerun.",
                },
                {
                  q: "I still need to publish a paper.",
                  a: "atlas paper:export turns a finished project into a draft seeded with methods, claims, evidence, plots, and citations.",
                },
                {
                  q: "Who owns the data?",
                  a: "You do. Your projects and data stay yours, and we don't train on your private work.",
                },
              ]}
            />
          </div>
        </div>
      </Section>

      {/* ============== FINAL CTA (blue dithered banner) =================== */}
      <section className="relative w-full overflow-hidden border-t border-border/40">
        <div className="mx-auto max-w-[1400px] w-full px-6 sm:px-10 py-20 sm:py-24">
          <div className="dither-blue border border-border/40 p-10 sm:p-16 min-h-[440px] flex flex-col justify-center relative">
            <div className="dither-content grid grid-cols-12 gap-10 items-center">
              <div className="col-span-12 lg:col-span-7">
                <Reveal>
                  <h2 className={`max-w-[14ch] text-balance ${H_HUGE} text-foreground`}>
                    Start with Atlas Graph.
                  </h2>
                </Reveal>
              </div>
              <div className="col-span-12 lg:col-span-5">
                <Reveal delay={200}>
                  <p className={`${P_BIG} text-foreground/80 max-w-[38ch]`}>
                    One command, and every run your agents make lands on the
                    record.
                  </p>
                  <div className="mt-8 flex flex-wrap items-center gap-3">
                    <Cta href="https://app.syntheticsciences.ai">Get started</Cta>
                    <InstallChip />
                  </div>
                </Reveal>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ============================== FOOTER ============================= */}
      <footer className="relative overflow-hidden">
        <div className={`mx-auto max-w-[1400px] px-6 sm:px-10 pt-16 pb-10 border-t border-border/40 ${LABEL}`}>
          <div className="grid grid-cols-12 gap-10">
            <div className="col-span-12 md:col-span-5">
              <div className="flex items-center gap-2.5 text-foreground">
                <AtlasMark size={15} />
                <span className="font-display text-[22px] tracking-tight leading-none">atlas</span>
              </div>
              <p className="mt-4 max-w-[34ch] text-[13.5px] leading-[1.7] text-foreground/55">
                Infrastructure for autonomous, open science, by Synthetic
                Sciences.
              </p>
            </div>
            <div className="col-span-6 sm:col-span-4 md:col-span-2">
              <div className="text-[13px] tracking-[0.04em] text-foreground/45 mb-4">Product</div>
              <ul className="space-y-2.5 text-[13.5px]">
                <li><a href="#graph" className="link-underline text-foreground/70 hover:text-foreground">Atlas Graph</a></li>
                <li><a href="#library" className="link-underline text-foreground/70 hover:text-foreground">Atlas Library</a></li>
              </ul>
            </div>
            <div className="col-span-6 sm:col-span-4 md:col-span-2">
              <div className="text-[13px] tracking-[0.04em] text-foreground/45 mb-4">Resources</div>
              <ul className="space-y-2.5 text-[13.5px]">
                <li><a href="https://docs.syntheticsciences.ai" className="link-underline text-foreground/70 hover:text-foreground" target="_blank" rel="noreferrer">Docs</a></li>
                <li><a href="#faq" className="link-underline text-foreground/70 hover:text-foreground">FAQ</a></li>
                <li><a href="https://docs.syntheticsciences.ai" className="link-underline text-foreground/70 hover:text-foreground" target="_blank" rel="noreferrer">Install the CLI</a></li>
              </ul>
            </div>
            <div className="col-span-12 sm:col-span-4 md:col-span-3">
              <div className="text-[13px] tracking-[0.04em] text-foreground/45 mb-4">Company</div>
              <ul className="space-y-2.5 text-[13.5px]">
                <li>
                  <a
                    href="https://syntheticsciences.ai"
                    className="link-underline text-foreground/70 hover:text-foreground inline-flex items-center gap-1.5"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Synthetic Sciences
                    <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden>
                      <path d="M2 8 L8 2 M4 2 L8 2 L8 6" stroke="currentColor" fill="none" />
                    </svg>
                  </a>
                </li>
                <li><a href="mailto:team@syntheticsciences.ai" className="link-underline text-foreground/70 hover:text-foreground">Careers</a></li>
                <li><a href="https://syntheticsciences.ai/privacy" className="link-underline text-foreground/70 hover:text-foreground" target="_blank" rel="noreferrer">Privacy</a></li>
                <li><a href="https://syntheticsciences.ai/terms" className="link-underline text-foreground/70 hover:text-foreground" target="_blank" rel="noreferrer">Terms</a></li>
              </ul>
            </div>
          </div>

          <div className="mt-14 pt-6 border-t border-border/40 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-[12.5px] text-foreground/45">
            <div>&copy; {new Date().getFullYear()} InkVell Inc. Atlas is a Synthetic Sciences product.</div>
            <a href="#top" className="link-underline hover:text-foreground inline-flex items-center gap-2">
              Back to top
              <svg width="9" height="11" viewBox="0 0 9 11" aria-hidden>
                <path d="M4.5 10V1.5M1 4.5 4.5 1 8 4.5" stroke="currentColor" fill="none" />
              </svg>
            </a>
          </div>
        </div>

        {/* Giant clipped wordmark, the closing brand moment. */}
        <div className="relative h-[15vw] min-h-[110px] max-h-[230px] overflow-hidden" aria-hidden>
          <div className="footer-watermark absolute left-1/2 -translate-x-1/2 top-[0.04em] text-center">
            atlas
          </div>
        </div>
      </footer>
    </div>
  );
}
