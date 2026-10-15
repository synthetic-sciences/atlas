import { FONT_MONO as mono, FONT_SANS as serif } from "../../styles/tokens.js";
import { parseSemanticData, scoreOf, scorecardOf } from "../graph/orbit.js";

/**
 * NodeStructured — surfaces a node's structured payload above the freeform
 * body, by kind. Empirical runs lead with their headline metric + a metrics
 * rail + the exact code state behind the run; decisions and hypotheses render
 * their typed fields (alternatives, basis, claim, rationale, disconfirmers)
 * instead of leaving them buried in semantic_data. Soft Porcelain throughout:
 * mono labels, Computer Modern values, hairline rules, 2px corners.
 */

interface StructuredNode {
  kind: string;
  outcome: string | null;
  summary: string | null;
  semantic_data?: Record<string, unknown> | string | null;
  repo_url: string | null;
  branch_name: string | null;
  head_commit_sha: string | null;
}

/* ── small shared atoms ───────────────────────────────────────────────── */

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontFamily: mono,
        fontSize: 9,
        fontWeight: 600,
        letterSpacing: "0.14em",
        textTransform: "uppercase",
        color: "var(--color-text-faint)",
      }}
    >
      {children}
    </div>
  );
}

function Chip({ children, color }: { children: React.ReactNode; color: string }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        padding: "2px 8px",
        borderRadius: 2,
        border: `1px solid ${color}`,
        background: "transparent",
        fontFamily: mono,
        fontSize: 9.5,
        fontWeight: 600,
        letterSpacing: "0.06em",
        color,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      <Label>{label}</Label>
      <div style={{ fontFamily: serif, fontSize: 14, lineHeight: 1.5, color: "var(--color-text)" }}>
        {children}
      </div>
    </div>
  );
}

function ListField({ label, items, accent }: { label: string; items: string[]; accent?: string }) {
  if (!items.length) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <Label>{label}</Label>
      <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 4 }}>
        {items.map((it, i) => (
          <li
            key={i}
            style={{
              fontFamily: serif,
              fontSize: 13.5,
              lineHeight: 1.45,
              color: "var(--color-text)",
              paddingLeft: 12,
              position: "relative",
            }}
          >
            <span
              style={{
                position: "absolute",
                left: 0,
                top: "0.62em",
                width: 4,
                height: 4,
                borderRadius: "50%",
                background: accent ?? "var(--color-text-faint)",
              }}
            />
            {it}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Shell: a hairline-bordered block with a kind-accent left edge. */
function Block({ accent, children }: { accent: string; children: React.ReactNode }) {
  return (
    <div
      style={{
        border: "1px solid var(--color-border)",
        borderLeft: `2px solid ${accent}`,
        borderRadius: 2,
        background: "var(--color-bg-subtle)",
        padding: "16px 18px",
        marginBottom: 22,
      }}
    >
      {children}
    </div>
  );
}

/* ── helpers ──────────────────────────────────────────────────────────── */

const strList = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === "string" && x.trim().length > 0) : [];

/** Format a metric value for display: ints plain, mfu/percent with %, else trimmed float. */
function fmtMetric(key: string, v: number): string {
  if (/percent|mfu|pct/i.test(key)) return `${Math.round(v * 100) / 100}%`;
  if (Number.isInteger(v)) return v.toLocaleString();
  if (Math.abs(v) >= 1000) return Math.round(v).toLocaleString();
  // keep small scores precise (val_bpb etc.), trim long tails
  return String(Math.round(v * 1e6) / 1e6);
}

const METRIC_LABEL: Record<string, string> = {
  val_bpb: "val_bpb",
  num_steps: "steps",
  total_tokens_m: "tokens (M)",
  mfu_percent: "mfu",
  wall_time_seconds: "wall (s)",
  training_seconds: "train (s)",
};

/** github.com/<owner>/<repo>/commit/<sha> when the repo is a github URL. */
function commitUrl(repo: string | null, sha: string | null): string | null {
  if (!repo || !sha) return null;
  const m = repo.replace(/\.git$/, "").match(/github\.com[/:]([^/]+\/[^/]+)/i);
  return m ? `https://github.com/${m[1]}/commit/${sha}` : null;
}

/* ── per-kind panels ──────────────────────────────────────────────────── */

function RunHeader({ node }: { node: StructuredNode }) {
  const sd = parseSemanticData(node) ?? {};
  const metricsRaw = sd.metrics;
  const metrics: [string, number][] = [];
  if (metricsRaw && typeof metricsRaw === "object" && !Array.isArray(metricsRaw)) {
    for (const [k, v] of Object.entries(metricsRaw as Record<string, unknown>)) {
      if (typeof v === "number" && Number.isFinite(v)) metrics.push([k, v]);
    }
  }
  const head = scoreOf(node);
  const sc = scorecardOf(node);
  const sha = node.head_commit_sha;
  const cUrl = commitUrl(node.repo_url, sha);
  const repoLabel = node.repo_url?.replace(/^https?:\/\//, "").replace(/\.git$/, "") ?? null;
  const accent = "var(--kind-empirical)";

  // Nothing structured to show -> render nothing (freeform body still appears).
  if (!metrics.length && !node.repo_url && !sc) return null;

  const railMetrics = metrics.filter(([k]) => !head || k !== head.metric);

  return (
    <Block accent={accent}>
      {head && (
        <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: railMetrics.length || node.repo_url ? 16 : 0 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            <Label>{METRIC_LABEL[head.metric] ?? head.metric}</Label>
            <div style={{ fontFamily: serif, fontSize: 30, fontWeight: 500, lineHeight: 1, color: "var(--color-text)" }}>
              {fmtMetric(head.metric, head.value)}
            </div>
          </div>
          <span style={{ fontFamily: mono, fontSize: 9.5, color: "var(--color-text-faint)", letterSpacing: "0.04em" }}>
            {head.lowerIsBetter ? "lower is better" : "higher is better"}
          </span>
        </div>
      )}

      {railMetrics.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 0, marginBottom: node.repo_url ? 16 : 0 }}>
          {railMetrics.map(([k, v], i) => (
            <div
              key={k}
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 3,
                padding: "0 16px",
                borderLeft: i === 0 ? "none" : "1px solid var(--color-border)",
              }}
            >
              <span style={{ fontFamily: mono, fontSize: 15, color: "var(--color-text)" }}>{fmtMetric(k, v)}</span>
              <span style={{ fontFamily: mono, fontSize: 9, letterSpacing: "0.06em", color: "var(--color-text-faint)" }}>
                {METRIC_LABEL[k] ?? k}
              </span>
            </div>
          ))}
        </div>
      )}

      {sc && sc.total > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: node.repo_url ? 16 : 0 }}>
          <Label>{sc.metric ? `scorecard · ${sc.metric}` : "scorecard"}</Label>
          <div style={{ display: "flex", gap: 1.5, alignItems: "center" }}>
            {sc.items.slice(0, 60).map((it, i) => (
              <span
                key={i}
                title={it.ref ?? undefined}
                style={{
                  width: 5,
                  height: 14,
                  borderRadius: 1,
                  background: it.pass ? "var(--color-success)" : "var(--color-error-muted)",
                  border: it.pass ? "none" : "1px solid var(--color-error)",
                }}
              />
            ))}
            <span style={{ fontFamily: mono, fontSize: 11, color: "var(--color-text-muted)", marginLeft: 8 }}>
              {sc.passed}/{sc.total}
            </span>
          </div>
        </div>
      )}

      {node.repo_url && (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: 8,
            fontFamily: mono,
            fontSize: 11,
            color: "var(--color-text-muted)",
            paddingTop: metrics.length || sc ? 14 : 0,
            borderTop: metrics.length || sc ? "1px solid var(--color-border)" : "none",
          }}
        >
          <span style={{ color: "var(--color-text)" }}>{repoLabel}</span>
          {node.branch_name && (
            <>
              <span style={{ color: "var(--color-text-faint)" }}>·</span>
              <span>⎇ {node.branch_name}</span>
            </>
          )}
          {sha && (
            <>
              <span style={{ color: "var(--color-text-faint)" }}>·</span>
              {cUrl ? (
                <a href={cUrl} target="_blank" rel="noreferrer" style={{ color: accent, textDecoration: "none" }}>
                  ◦ {sha.slice(0, 7)} ↗
                </a>
              ) : (
                <span>◦ {sha.slice(0, 7)}</span>
              )}
            </>
          )}
        </div>
      )}
    </Block>
  );
}

const HYP_STATUS_COLOR: Record<string, string> = {
  proposed: "var(--color-text-muted)",
  testing: "var(--color-warning)",
  supported: "var(--color-success)",
  weakened: "var(--color-warning)",
  rejected: "var(--color-error)",
};

function HypothesisPanel({ node }: { node: StructuredNode }) {
  const sd = parseSemanticData(node) ?? {};
  const claim = (typeof sd.claim === "string" && sd.claim) || node.summary || null;
  const rationale = typeof sd.rationale === "string" ? sd.rationale : null;
  const status = typeof sd.status === "string" ? sd.status : null;
  const assumptions = strList(sd.assumptions);
  const expected = strList(sd.expected_observations);
  const disconfirmers = strList(sd.disconfirmers);
  if (!claim && !rationale && !assumptions.length && !expected.length && !disconfirmers.length) return null;
  const accent = "var(--kind-hypothesis)";

  return (
    <Block accent={accent}>
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {status && (
          <div>
            <Chip color={HYP_STATUS_COLOR[status] ?? "var(--color-text-muted)"}>{status}</Chip>
          </div>
        )}
        {claim && (
          <div style={{ fontFamily: serif, fontSize: 17, lineHeight: 1.4, color: "var(--color-text)", fontStyle: "italic" }}>
            {claim}
          </div>
        )}
        {rationale && <Field label="rationale">{rationale}</Field>}
        <ListField label="assumptions" items={assumptions} accent={accent} />
        <ListField label="expected observations" items={expected} accent="var(--color-success)" />
        <ListField label="what would disconfirm it" items={disconfirmers} accent="var(--color-error)" />
      </div>
    </Block>
  );
}

function DecisionPanel({ node }: { node: StructuredNode }) {
  const sd = parseSemanticData(node) ?? {};
  const decision = node.summary || null;
  const alternatives = strList(sd.alternatives);
  const confidence = typeof sd.confidence === "string" ? sd.confidence : null;
  const reversible = typeof sd.reversible === "boolean" ? sd.reversible : null;
  const basis = Array.isArray(sd.basis_node_ids) ? sd.basis_node_ids.length : 0;
  if (!decision && !alternatives.length && confidence == null && reversible == null) return null;
  const accent = "var(--kind-decision)";

  return (
    <Block accent={accent}>
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {decision && (
          <div style={{ fontFamily: serif, fontSize: 17, lineHeight: 1.4, color: "var(--color-text)" }}>{decision}</div>
        )}
        {(confidence || reversible != null || basis > 0) && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {confidence && <Chip color={accent}>{confidence} confidence</Chip>}
            {reversible != null && (
              <Chip color={reversible ? "var(--color-success)" : "var(--color-warning)"}>
                {reversible ? "reversible" : "one-way"}
              </Chip>
            )}
            {basis > 0 && <Chip color="var(--color-text-muted)">rests on {basis}</Chip>}
          </div>
        )}
        <ListField label="alternatives considered" items={alternatives} accent={accent} />
      </div>
    </Block>
  );
}

function PlanPanel({ node }: { node: StructuredNode }) {
  const sd = parseSemanticData(node) ?? {};
  if (sd.type !== "experiment_plan") return null;
  const metric = typeof sd.metric === "string" ? sd.metric : null;
  const criterion = typeof sd.success_criterion === "string" ? sd.success_criterion : null;
  const expected = typeof sd.expected_result === "string" ? sd.expected_result : null;
  const risks = strList(sd.risks);
  if (!metric && !criterion && !expected && !risks.length) return null;
  const accent = "var(--kind-hypothesis)";

  return (
    <Block accent={accent}>
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {criterion && (
          <Field label="success criterion">
            <code style={{ fontFamily: mono, fontSize: 13, color: "var(--color-text)" }}>{criterion}</code>
          </Field>
        )}
        {metric && <Field label="metric">{metric}</Field>}
        {expected && <Field label="expected result">{expected}</Field>}
        <ListField label="risks" items={risks} accent="var(--color-warning)" />
      </div>
    </Block>
  );
}

/** Dispatcher: pick the structured panel for this node's kind, if any. */
export function NodeStructured({ node }: { node: StructuredNode }) {
  const sd = parseSemanticData(node);
  const stype = sd && typeof sd.type === "string" ? sd.type : null;

  if (node.kind === "empirical" || (sd && "metrics" in sd) || node.repo_url) return <RunHeader node={node} />;
  if (node.kind === "hypothesis" || stype === "hypothesis") return <HypothesisPanel node={node} />;
  if (node.kind === "decision" || stype === "decision") return <DecisionPanel node={node} />;
  if (stype === "experiment_plan") return <PlanPanel node={node} />;
  return null;
}
