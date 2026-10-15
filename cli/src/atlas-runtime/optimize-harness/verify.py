#!/usr/bin/env python3
"""Gateway optimize referee: N-seed replication of a recorded candidate.

A single search-time score is a noisy point estimate; nothing should be
claimed from it. ``optimize:verify`` re-runs the candidate's benchmark N
times at the candidate's exact commit (``head_commit_sha``), with
``ATLAS_EVAL_SEED=0..N-1`` exported for the benchmark to consume, then:

- records every replication as a run under the control node, folded into
  one cluster (``verify/<candidate>``),
- computes mean / std / min / max and, when ``--threshold`` is given, a
  one-sided one-sample t-test (scipy-free) that the mean beats the
  threshold in the metric's direction,
- attaches a referee-report node (insight) with the verdict and the full
  per-seed table.

Works for any benchmark following the contract in
``../references/benchmark-contract.md`` — nothing here is task-specific.

Invoked by ``atlas optimize:verify`` or directly:

    python verify.py --node <candidate-or-control> \
        --benchmark "python eval.py --candidate {target}" \
        --metric min --seeds 10 --threshold 0.92 --alpha 0.01
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atlas_gepa import atlas_json, node_id_of  # noqa: E402
from optimize import add_worktree, read_result, remove_worktree, repo_root  # noqa: E402


# --------------------------------------------------------------------------- #
# one-sided one-sample t-test (scipy-free)
# --------------------------------------------------------------------------- #
def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Lentz)."""
    max_it, eps, fpmin = 300, 3e-12, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, max_it + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def reg_inc_beta(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_front = (
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log(1.0 - x)
    )
    front = math.exp(ln_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_cdf(t: float, df: int) -> float:
    """P(T <= t) for Student's t with df degrees of freedom."""
    x = df / (df + t * t)
    tail = 0.5 * reg_inc_beta(df / 2.0, 0.5, x)
    return tail if t < 0 else 1.0 - tail


def one_sided_p(scores: list[float], threshold: float, better: str) -> float | None:
    """p-value that the true mean beats `threshold` in the better direction.

    better="min": H1 is mean < threshold (p = P(T <= t)).
    better="max": H1 is mean > threshold (p = P(T >= t)).
    """
    n = len(scores)
    if n < 2:
        return None
    mean = statistics.mean(scores)
    sd = statistics.stdev(scores)
    if sd == 0:
        beats = mean < threshold if better == "min" else mean > threshold
        return 0.0 if beats else 1.0
    t = (mean - threshold) / (sd / math.sqrt(n))
    return t_cdf(t, n - 1) if better == "min" else 1.0 - t_cdf(t, n - 1)


# --------------------------------------------------------------------------- #
# node plumbing
# --------------------------------------------------------------------------- #
def fetch_node(node_id: str) -> dict[str, Any]:
    node = atlas_json(["node:show", "--node", node_id])
    return node.get("node") or node


def semantics_of(node: dict[str, Any]) -> dict[str, Any]:
    sem = node.get("semantic_data") or {}
    if isinstance(sem, str):
        try:
            sem = json.loads(sem)
        except json.JSONDecodeError:
            sem = {}
    return sem if isinstance(sem, dict) else {}


def resolve_candidate(node_id: str) -> tuple[dict[str, Any], str | None]:
    """Accept a candidate node or a control node (uses its best candidate).
    Returns (candidate_node, control_node_id_if_known)."""
    node = fetch_node(node_id)
    sem = semantics_of(node)
    if sem.get("type") == "optimize_run":
        best = sem.get("best_node_id")
        if not best:
            raise SystemExit("error: control node has no best_node_id to verify yet")
        return fetch_node(str(best)), str(node.get("node_id") or node_id)
    return node, None


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def run(args: argparse.Namespace) -> int:
    if not os.environ.get("ATLAS_API_KEY"):
        print("error: ATLAS_API_KEY is not set", file=sys.stderr)
        return 2

    root = repo_root()
    candidate, control_from_node = resolve_candidate(args.node)
    candidate_id = str(candidate.get("node_id") or args.node)
    sha = candidate.get("head_commit_sha")
    if not sha:
        raise SystemExit(
            "error: candidate has no head_commit_sha — only harness-recorded "
            "candidates (with code-state commits) can be verified"
        )
    record_under = args.project or control_from_node
    if not record_under:
        parents = candidate.get("parent_ids") or []
        record_under = str(parents[0]) if parents else None
    cluster = args.cluster or f"verify/{candidate_id}"
    better = "min" if args.metric == "min" else "max"

    print(
        f"[verify] candidate {candidate_id} @ {str(sha)[:12]} · {args.seeds} seeds · "
        f"metric {better}" + (f" · threshold {args.threshold}" if args.threshold is not None else ""),
        file=sys.stderr,
    )

    target_rel = None
    scores: list[float] = []
    reps: list[dict[str, Any]] = []
    for seed in range(args.seeds):
        wt = root / ".atlas-optimize" / "verify" / uuid.uuid4().hex[:12]
        rep: dict[str, Any] = {"seed": seed}
        try:
            add_worktree(root, wt, ref=str(sha))
            result_file = wt / ".atlas-optimize-result.json"
            env = os.environ.copy()
            env["ATLAS_EVAL_SEED"] = str(seed)
            env["ATLAS_OPTIMIZE_RESULT"] = str(result_file)
            cmd = args.benchmark.replace("{worktree}", str(wt))
            if "{target}" in cmd:
                # The contract's {target} is the artifact path; under verify the
                # artifact already sits in the tree at the candidate's commit.
                target_rel = args.target or _guess_target(candidate)
                if not target_rel:
                    raise SystemExit(
                        "error: benchmark uses {target} — pass --target <repo-relative path>"
                    )
                target_abs = wt / target_rel
                env["ATLAS_OPTIMIZE_TARGET"] = str(target_abs)
                cmd = cmd.replace("{target}", str(target_abs))

            started = time.time()
            try:
                proc = subprocess.run(cmd, cwd=wt, shell=True, env=env,
                                      capture_output=True, text=True, timeout=args.benchmark_timeout)
            except subprocess.TimeoutExpired:
                rep.update(outcome="failure", error="benchmark_timeout")
                reps.append(rep)
                _record_rep(record_under, candidate_id, cluster, rep, None, sha, candidate)
                continue
            rep["wall_seconds"] = round(time.time() - started, 1)

            if proc.returncode != 0:
                rep.update(outcome="failure", error=f"benchmark_exit_{proc.returncode}",
                           stderr=(proc.stderr or "")[-1500:])
                reps.append(rep)
                _record_rep(record_under, candidate_id, cluster, rep, None, sha, candidate)
                continue

            try:
                score, _parsed = read_result(result_file, proc.stdout)
            except (ValueError, json.JSONDecodeError) as exc:
                rep.update(outcome="failure", error=f"bad_result: {exc}")
                reps.append(rep)
                _record_rep(record_under, candidate_id, cluster, rep, None, sha, candidate)
                continue

            failed_gates = []
            for gate in args.gate or []:
                gate_cmd = gate.replace("{worktree}", str(wt))
                if "{target}" in gate_cmd and target_rel:
                    gate_cmd = gate_cmd.replace("{target}", str(wt / target_rel))
                try:
                    g = subprocess.run(gate_cmd, cwd=wt, shell=True, env=env,
                                       capture_output=True, text=True, timeout=args.benchmark_timeout)
                    if g.returncode != 0:
                        failed_gates.append(gate)
                except subprocess.TimeoutExpired:
                    failed_gates.append(f"{gate} (timeout)")
            if failed_gates:
                rep.update(outcome="failure", error=f"gate failed: {'; '.join(failed_gates)[:300]}",
                           score=score)
                reps.append(rep)
                _record_rep(record_under, candidate_id, cluster, rep, score, sha, candidate)
                continue

            rep.update(outcome="success", score=score)
            scores.append(score)
            reps.append(rep)
            _record_rep(record_under, candidate_id, cluster, rep, score, sha, candidate)
            print(f"[verify] seed {seed}: {score:g}", file=sys.stderr)
        finally:
            remove_worktree(root, wt)

    failures = [r for r in reps if r.get("outcome") != "success"]
    summary: dict[str, Any] = {
        "candidate_node": candidate_id,
        "head_commit_sha": sha,
        "seeds": args.seeds,
        "succeeded": len(scores),
        "failed": len(failures),
        "cluster": cluster,
        "metric": better,
        "scores": scores,
    }
    if scores:
        summary["mean"] = statistics.mean(scores)
        summary["min"] = min(scores)
        summary["max"] = max(scores)
        if len(scores) >= 2:
            summary["std"] = statistics.stdev(scores)
    if args.threshold is not None and len(scores) >= 2:
        p = one_sided_p(scores, args.threshold, better)
        summary["threshold"] = args.threshold
        summary["alpha"] = args.alpha
        summary["p_value"] = p
        summary["verified"] = bool(p is not None and p < args.alpha and not failures)
    elif failures:
        summary["verified"] = False

    report_node = _attach_report(record_under, candidate, summary, reps, args)
    if report_node:
        summary["report_node"] = report_node

    print(json.dumps(summary))
    return 0 if summary.get("verified", True) else 1


def _guess_target(candidate: dict[str, Any]) -> str | None:
    """Harness-recorded candidates carry the run's target via the control
    node contract; fall back to the run config when present."""
    sem = semantics_of(candidate)
    run = sem.get("run") if isinstance(sem.get("run"), dict) else {}
    config = run.get("config") if isinstance(run.get("config"), dict) else {}
    target = config.get("target")
    return str(target) if target else None


def _record_rep(project: str | None, candidate_id: str, cluster: str,
                rep: dict[str, Any], score: float | None, sha: Any,
                candidate: dict[str, Any]) -> None:
    if not project:
        return
    body: dict[str, Any] = {
        "project_id": project,
        "title": f"verify {candidate_id[:12]} · seed {rep['seed']}"
        + (f" · {score:g}" if isinstance(score, (int, float)) else " · FAILED"),
        "outcome": "success" if rep.get("outcome") == "success" else "failure",
        "config": {"seed": rep["seed"], "verify_of": candidate_id},
        "metrics": {"score": score} if isinstance(score, (int, float)) else None,
        "run_cluster_key": cluster,
        "head_commit_sha": str(sha),
        "branch_name": candidate.get("branch_name"),
        "repo_url": candidate.get("repo_url"),
    }
    if rep.get("outcome") != "success":
        body["failure_mode"] = "other"
        body["stdout_tail"] = str(rep.get("error", ""))[:1500]
    body = {k: v for k, v in body.items() if v is not None}
    try:
        atlas_json(["run:record", "--payload-json", json.dumps(body)])
    except Exception as exc:  # noqa: BLE001
        print(f"[verify] replication record failed: {exc}", file=sys.stderr)


def _attach_report(project: str | None, candidate: dict[str, Any],
                   summary: dict[str, Any], reps: list[dict[str, Any]],
                   args: argparse.Namespace) -> str | None:
    if not project:
        return None
    rows = "\n".join(
        f"| {r['seed']} | {r.get('score', '—')} | {r.get('outcome')} |" for r in reps
    )
    verdict = summary.get("verified")
    verdict_line = (
        "**VERIFIED** — mean beats the threshold at the pre-registered alpha"
        if verdict is True
        else "**NOT VERIFIED**" if verdict is False
        else "no threshold given — stats only"
    )
    stats_lines = [
        f"- n succeeded: {summary['succeeded']} / {summary['seeds']}",
        f"- mean: {summary.get('mean', '—')}",
        f"- std: {summary.get('std', '—')}",
        f"- min / max: {summary.get('min', '—')} / {summary.get('max', '—')}",
    ]
    if "p_value" in summary:
        stats_lines.append(
            f"- one-sided t-test vs {summary['threshold']} ({summary['metric']}): "
            f"p = {summary['p_value']:.6g} (alpha {summary['alpha']})"
        )
    content = (
        f"## Referee report\n\n"
        f"Replication of candidate `{summary['candidate_node']}` at commit "
        f"`{str(summary['head_commit_sha'])[:12]}` — {summary['seeds']} seeds, "
        f"`ATLAS_EVAL_SEED` exported per run, fresh worktree + process per run.\n\n"
        f"{verdict_line}\n\n"
        + "\n".join(stats_lines)
        + f"\n\n- benchmark: `{args.benchmark}`\n"
        + (f"- gates: {len(args.gate)} enforced per seed\n" if args.gate else "")
        + f"- run cluster: `{summary['cluster']}`\n\n"
        f"| seed | score | outcome |\n|---|---|---|\n{rows}\n"
    )
    title_score = f" · mean {summary['mean']:g}" if "mean" in summary else ""
    envelope = {
        "local_temp_node_id": f"verify-{uuid.uuid4().hex[:10]}",
        "parent_ids": [project],
        "staged_payload": {
            "title": f"referee report: {summary['candidate_node'][:12]} (n={summary['seeds']}){title_score}",
            "summary": verdict_line.replace("*", ""),
            "content": content,
            "kind": "insight",
            "insights": [verdict_line.replace("*", "")],
            "outcome": "completed" if verdict is not False else "failed",
        },
    }
    try:
        return node_id_of(atlas_json(["node:create"], envelope))
    except Exception as exc:  # noqa: BLE001
        print(f"[verify] report node failed: {exc}", file=sys.stderr)
        return None


def main() -> int:
    p = argparse.ArgumentParser(description="Replicate a recorded candidate N times and referee the result.")
    p.add_argument("--node", required=True, help="candidate node, or a control node (verifies its best)")
    p.add_argument("--benchmark", required=True, help="shell command; {target}/{worktree} substituted")
    p.add_argument("--metric", choices=["max", "min"], default="max")
    p.add_argument("--seeds", type=int, default=10)
    p.add_argument("--threshold", type=float, default=None,
                   help="success criterion the mean must beat (one-sided t-test)")
    p.add_argument("--alpha", type=float, default=0.01)
    p.add_argument("--gate", action="append", default=[], help="gate command per seed; exit 0 = pass")
    p.add_argument("--cluster", default=None, help="run_cluster_key (default verify/<candidate>)")
    p.add_argument("--project", default=None, help="node to record replications under (default: the control)")
    p.add_argument("--target", default=None, help="repo-relative artifact path when the benchmark uses {target}")
    p.add_argument("--benchmark-timeout", type=int, default=900, dest="benchmark_timeout")
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
