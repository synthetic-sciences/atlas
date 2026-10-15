// Pure helpers + generated-file templates for `atlas autoresearch`.
//
// The orchestration (project resolve, pre-register, search, referee, report)
// lives in local-commands.mjs alongside optimize:start/verify; everything here
// is deterministic and side-effect-free so it can be unit-tested directly and
// reused by the orchestrator without a circular import.

// --------------------------------------------------------------------------- //
// goal parsing
// --------------------------------------------------------------------------- //

// Words that signal the metric direction in a plain-English goal. Inference is
// only a default — the resolved direction is always shown for confirmation and
// can be overridden with --metric.
const MIN_SIGNALS = /\b(reduce|reducing|lower|minimi[sz]e?|minimi[sz]ing|decrease|decreasing|shrink|cut|cutting|fewer|less|drop|speed[\s-]?up|faster|speedup|loss|losses|bpb|nll|perplexity|ppl|error|errors|latency|runtime|wall[\s-]?clock|memory|cost|costs|time|regret)\b/;
const MAX_SIGNALS = /\b(raise|raising|improve|improving|increase|increasing|maximi[sz]e?|maximi[sz]ing|boost|beat|beating|higher|more|better|accuracy|acc|score|scores|f1|reward|rewards|throughput|pass(?:@\d+|[\s-]?rate)?|win[\s-]?rate|wins?|recall|precision|bleu|rouge|auc|map|psnr|ssim|success)\b/;

export function inferMetricDirection(goal) {
  const g = String(goal || "").toLowerCase();
  const min = MIN_SIGNALS.test(g);
  const max = MAX_SIGNALS.test(g);
  if (min && !max) return "min";
  if (max && !min) return "max";
  if (min && max) {
    // Both fired (e.g. "reduce loss to improve accuracy"). Prefer the loss/error
    // family since that is almost always the optimized quantity in such phrasing.
    return /\b(loss|bpb|nll|perplexity|ppl|error|latency|cost|regret)\b/.test(g) ? "min" : "max";
  }
  return "max"; // nothing matched: harmless default, surfaced for confirmation
}

// Known metric tokens, longest/most-specific first so "val_bpb" wins over "bpb".
const KNOWN_METRICS = [
  "perplexity", "throughput", "precision", "accuracy", "latency", "f1_score",
  "win_rate", "pass_rate", "val_loss", "val_bpb", "val_acc", "reward",
  "recall", "bleu", "rouge", "psnr", "ssim", "auc", "nll", "ppl", "bpb",
  "acc", "f1", "loss", "error", "score", "cost", "wer", "cer", "map",
];

// The metric token to grep out of a run's output. Prefer an explicit
// snake_case / slash token from the goal (val_bpb, eval/acc); else a known
// single-word metric; else null (signals "can't tell — scaffold and stop").
export function deriveMetricToken(goal) {
  const g = String(goal || "").toLowerCase();
  const snakeTokens = (g.match(/\b[a-z]+(?:[_/][a-z0-9]+)+\b/g) || []).map((t) => t.replace(/\//g, "_"));
  // A snake token that itself contains a known metric word is the strongest signal.
  for (const tok of snakeTokens) {
    if (KNOWN_METRICS.some((m) => tok.includes(m))) return tok;
  }
  for (const m of KNOWN_METRICS) {
    if (new RegExp(`\\b${m}\\b`).test(g)) return m;
  }
  return snakeTokens[0] || null;
}

// "8h" / "30m" / "90s" / "2d" -> seconds. Bare number defaults to seconds.
export function parseDurationSeconds(raw) {
  const s = String(raw == null ? "" : raw).trim().toLowerCase();
  const m = s.match(/^(\d+(?:\.\d+)?)\s*(s|sec|secs|seconds?|m|min|mins|minutes?|h|hr|hrs|hours?|d|days?)?$/);
  if (!m) throw new Error(`--budget must look like 8h / 30m / 90s / 2d (got "${raw}")`);
  const n = parseFloat(m[1]);
  const unit = (m[2] || "s")[0];
  const mult = { s: 1, m: 60, h: 3600, d: 86400 }[unit];
  return Math.round(n * mult);
}

// The pre-registered success criterion: the verified mean must beat the
// measured baseline in the metric's direction. Bound to the plan before the
// first candidate so the comparison is honest, not chosen after seeing results.
export function buildSuccessCriterion({ metric, baseline, seeds, alpha }) {
  const op = metric === "min" ? "<" : ">";
  const base = typeof baseline === "number" && Number.isFinite(baseline)
    ? formatNumber(baseline)
    : "the baseline";
  return `verified mean ${op} ${base} (metrics.score) at alpha ${alpha}, n >= ${seeds}`;
}

export function formatNumber(x) {
  if (typeof x !== "number" || !Number.isFinite(x)) return String(x);
  // Compact but lossless-ish: trim trailing zeros, keep up to 6 sig digits.
  const s = Math.abs(x) >= 1e-4 && Math.abs(x) < 1e6 ? x.toFixed(6) : x.toExponential(4);
  return s.replace(/(\.\d*?)0+($|e)/i, "$1$2").replace(/\.$/, "").replace(/\.(e)/i, "$1");
}

// --------------------------------------------------------------------------- //
// generated benchmark scaffold (the researchify automation)
// --------------------------------------------------------------------------- //

// The command that produces a candidate's run output, given what we detected.
// Prefer the repo's own run script; else run a python target directly; else
// null (we cannot infer how to run it — scaffold-and-stop).
export function resolveRunCommand({ detectedRunCommand, target }) {
  if (detectedRunCommand) return detectedRunCommand;
  if (target && /\.py$/i.test(target)) return 'python3 "$ATLAS_OPTIMIZE_TARGET"';
  return null;
}

export function renderBenchmarkSh({ runCommand, target }) {
  return `#!/usr/bin/env bash
# Generated by \`atlas autoresearch\` — this file is YOURS, edit it freely.
#
# Contract: write {"score": <float>, "examples": [...]} to \$ATLAS_OPTIMIZE_RESULT.
# The candidate artifact has already been written into this worktree at
#   \${ATLAS_OPTIMIZE_TARGET}   (the repo-relative path: ${target})
# so the only thing a candidate can change is that file — the optimizer runs
# every candidate in its own throwaway git worktree, which keeps the evaluator
# and data pinned. score.py turns the run's output into the score; .atlas/gate.sh
# is the Goodhart guard.
set -uo pipefail
HERE="$(cd "$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
OUT="$(mktemp)"

# --- the repo's run command (auto-detected) --------------------------------
# Edit this line if the campaign should run something different.
( ${runCommand} ) >"$OUT" 2>&1
RC=$?
# ---------------------------------------------------------------------------

if [ "$RC" -ne 0 ]; then
  echo "[benchmark] run command exited $RC — candidate failed" >&2
  tail -n 40 "$OUT" >&2
  exit "$RC"
fi

# Parse the optimized metric out of the run output (edit .atlas/score.py to
# change which number is read, or to emit richer per-example feedback).
python3 "$HERE/score.py" --stdout "$OUT"
`;
}

export function renderScorePy({ metricToken, metric }) {
  const higher = metric === "min" ? "False" : "True";
  const token = metricToken || "score";
  return `#!/usr/bin/env python3
"""Generated by \`atlas autoresearch\`. Parse one metric out of a run's output
into the Gateway benchmark contract.

EDIT the METRIC line if the wrong number is being read, or rewrite parse() for
a richer evaluator (per-example feedback is what makes GEPA converge — see
.atlas/benchmark-contract)."""
import argparse
import json
import os
import re
import sys

# autoresearch guessed this metric name from your --goal.
METRIC = ${JSON.stringify(token)}          # <-- EDIT ME if this is the wrong metric
HIGHER_IS_BETTER = ${higher}

# Matches "<metric> = 0.74", "<metric>: 0.74", "<metric> 0.74".
PATTERN = re.compile(
    re.escape(METRIC) + r"\\s*[:=]?\\s*([+-]?[0-9]*\\.?[0-9]+(?:[eE][+-]?[0-9]+)?)"
)


def parse(text):
    matches = PATTERN.findall(text)
    if not matches:
        return None
    return float(matches[-1])  # last occurrence == final epoch / final eval


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stdout", required=True, help="file holding the run's captured output")
    args = ap.parse_args()
    text = open(args.stdout, encoding="utf-8", errors="replace").read()
    score = parse(text)
    if score is None:
        sys.stderr.write(
            f"[score] could not find metric '{METRIC}' in the run output.\\n"
            "        Fix: edit .atlas/score.py (METRIC=...), or pass an explicit\\n"
            "        --benchmark to 'atlas autoresearch'.\\n"
        )
        sys.exit(3)
    direction = "higher is better" if HIGHER_IS_BETTER else "lower is better"
    result = {
        "score": score,
        "examples": [{
            "id": METRIC,
            "score": score,
            "pass": True,
            "feedback": f"{METRIC} = {score} (parsed from run output; {direction})",
        }],
        "feedback": f"Final {METRIC} = {score}.",
    }
    out = os.environ.get("ATLAS_OPTIMIZE_RESULT")
    payload = json.dumps(result)
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(payload)
    else:
        sys.stdout.write(payload)


if __name__ == "__main__":
    main()
`;
}

export function renderGateSh() {
  return `#!/usr/bin/env bash
# Generated by \`atlas autoresearch\` — the Goodhart guard.
#
# A candidate may only change the artifact under test. If a run modifies any
# OTHER tracked file (e.g. rewrites the evaluator or test data to fake a pass),
# this gate fails (exit non-zero) and the candidate is scored worst, so the
# Pareto front never elevates a cheat. Relax IGNORE_RE if your run legitimately
# rewrites tracked files (checkpoints, logs, and .atlas/ are already ignored).
set -uo pipefail
WT="\${1:-$PWD}"
TARGET="\${2:-\${ATLAS_OPTIMIZE_TARGET:-}}"
REL="\${TARGET#"$WT"/}"
IGNORE_RE='^(outputs/|out/|checkpoints/|runs/|wandb/|\\.atlas/|.*\\.log$|.*\\.ckpt$|.*\\.pt$|.*\\.bin$|.*\\.safetensors$)'
CHANGED="$(git -C "$WT" status --porcelain --untracked-files=no 2>/dev/null \\
  | sed 's/^...//' \\
  | { [ -n "$REL" ] && grep -vF -- "$REL" || cat; } \\
  | grep -Ev "$IGNORE_RE" || true)"
if [ -n "$CHANGED" ]; then
  echo "[gate] the run modified tracked files other than the candidate:" >&2
  echo "$CHANGED" >&2
  exit 1
fi
exit 0
`;
}
