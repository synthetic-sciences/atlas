#!/usr/bin/env python3
"""Gateway optimize harness: GEPA's `optimize_anything` over a file artifact,
with every candidate persisted into the Gateway map.

Architecture (see ../references/gepa-atlas.md):

- ``AtlasCallback`` (atlas_gepa.py) observes the run and records candidate
  nodes with lineage + scorecards, streams budget/best to the control node,
  and attaches reflection provenance. This file owns the *evaluator* side:
  git-worktree isolation, the benchmark contract, gates, and code-state
  capture (every evaluated candidate becomes a reachable commit under
  ``refs/atlas/optimize/…``).
- ``GroundedProposer`` (optional, --ground) folds Gateway web-search snippets
  into GEPA's reflection prompt when the search stalls.

Invoked by ``atlas optimize:start`` or directly:

    uv run --with gepa python optimize.py \
        --target prompts/classify.txt \
        --benchmark "python eval.py --candidate {target}" \
        --metric max \
        --objective "maximize spam-classification F1 on the holdout set" \
        [--gate "pytest tests/core -x"] [--ground] \
        [--project <node>] [--resume <control-node>] \
        --max-metric-calls 50 --stall 5

Environment:
    ATLAS_API_KEY        required (used by the `atlas` CLI for persistence)
    <reflection LM key>  e.g. OPENAI_API_KEY / ANTHROPIC_API_KEY

Benchmark contract (../references/benchmark-contract.md): the command is
run inside the candidate's worktree with {target} substituted; it writes
``{"score": float, "examples": [{id, score, pass, feedback}, …]}`` to
``$ATLAS_OPTIMIZE_RESULT`` (or stdout). Rich per-example feedback is what
GEPA reflects on — flat scores optimize slowly.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atlas_gepa import (  # noqa: E402
    AtlasCallback,
    EvaluatorRegistry,
    GroundedProposer,
    atlas_json,
    node_id_of,
)

BENCHMARK_TIMEOUT_DEFAULT = 900  # seconds, per candidate
GEPA_WORST = -1e12  # handed to GEPA on any failure (it assumes higher-is-better)


class DeadlineStopper:
    """Wall-clock budget stopper.

    Mirrors GEPA's callable stop-condition protocol (the same shape as
    ``FileStopper``): returns True once a deadline passes, so the search
    stops at the next iteration boundary. GEPA's released stop conditions
    are metric-call / no-improvement only; this adds the "give it a
    wall-clock budget and walk away" mode (`atlas autoresearch --budget 8h`)
    the field treats as table stakes for overnight autonomy.
    """

    def __init__(self, seconds: float) -> None:
        self.deadline = time.time() + max(0.0, float(seconds))

    def __call__(self, gepa_state: Any = None) -> bool:
        return time.time() >= self.deadline


# --------------------------------------------------------------------------- #
# git plumbing
# --------------------------------------------------------------------------- #
def git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def repo_root() -> Path:
    return Path(git(["rev-parse", "--show-toplevel"], Path.cwd()))


def add_worktree(root: Path, wt: Path, ref: str = "HEAD") -> None:
    """`git worktree add` with retries: concurrent adds contend on git's
    ref locks under --parallel, and a transient lock is not a failure."""
    wt.parent.mkdir(parents=True, exist_ok=True)
    last: Exception | None = None
    for attempt in range(4):
        try:
            git(["worktree", "add", "--detach", str(wt), ref], cwd=root)
            return
        except subprocess.CalledProcessError as exc:
            last = exc
            time.sleep(0.25 * (attempt + 1))
    raise last  # type: ignore[misc]


def remove_worktree(root: Path, wt: Path) -> None:
    subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=root, check=False)
    subprocess.run(["git", "worktree", "prune"], cwd=root, check=False)


def commit_candidate(root: Path, wt: Path, run_id: str, n: int) -> str | None:
    """Capture the candidate's exact tree as a reachable commit.

    Commits on the worktree's detached HEAD, then anchors the sha under
    ``refs/atlas/optimize/<run>/cand-<n>`` so it survives worktree removal
    without polluting ``git branch``. Best-effort: a git hiccup must not
    fail the evaluation.
    """
    try:
        subprocess.run(["git", "add", "-A"], cwd=wt, check=True, capture_output=True)
        status = git(["status", "--porcelain"], cwd=wt)
        if status.strip():
            subprocess.run(
                ["git", "commit", "-m", f"atlas optimize: candidate {n}", "--no-verify"],
                cwd=wt, check=True, capture_output=True,
            )
        sha = git(["rev-parse", "HEAD"], cwd=wt)
        git(["update-ref", f"refs/atlas/optimize/{run_id}/cand-{n}", sha], cwd=root)
        return sha
    except subprocess.CalledProcessError as exc:
        print(f"[optimize] candidate commit failed: {exc.stderr or exc}", file=sys.stderr)
        return None


def remote_url(root: Path) -> str | None:
    try:
        return git(["remote", "get-url", "origin"], cwd=root)
    except subprocess.CalledProcessError:
        return None


def file_at_commit(root: Path, sha: str, rel: str) -> str | None:
    proc = subprocess.run(
        ["git", "show", f"{sha}:{Path(rel).as_posix()}"],
        cwd=root, capture_output=True, text=True,
    )
    return proc.stdout if proc.returncode == 0 else None


def best_candidate_seed(control: str, target_rel: str, root: Path) -> tuple[str, str] | None:
    """Resume-from-best: pull the best recorded candidate's exact content
    from the map (best_node_id -> head_commit_sha -> `git show`). Returns
    (seed_text, best_node_id) or None when unavailable."""
    try:
        node = atlas_json(["node:show", "--node", control])
        node = node.get("node") or node
        sem = node.get("semantic_data") or {}
        if isinstance(sem, str):
            sem = json.loads(sem)
        best = sem.get("best_node_id")
        if not best:
            return None
        best_node = atlas_json(["node:show", "--node", str(best)])
        best_node = best_node.get("node") or best_node
        sha = best_node.get("head_commit_sha")
        if not sha:
            return None
        content = file_at_commit(root, str(sha), target_rel)
        return (content, str(best)) if content else None
    except Exception as exc:  # noqa: BLE001
        print(f"[optimize] resume-from-best lookup failed: {exc}", file=sys.stderr)
        return None


# --------------------------------------------------------------------------- #
# benchmark result parsing
# --------------------------------------------------------------------------- #
def read_result(result_file: Path, stdout: str) -> tuple[float, dict[str, Any]]:
    raw = result_file.read_text(encoding="utf-8") if result_file.exists() else stdout.strip()
    if not raw.strip():
        raise ValueError("benchmark produced no result JSON")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict) or "score" not in parsed:
        raise ValueError("result JSON missing 'score'")
    return float(parsed["score"]), parsed


def parse_search_seeds(raw: str | None) -> list[int | None]:
    """Seeds used inside search-time candidate scoring.

    The default is the historical single benchmark call with no
    ATLAS_EVAL_SEED override. Passing "0,1,2" turns one GEPA candidate
    evaluation into three benchmark replications and aggregates them before
    GEPA sees the score.
    """
    if not raw:
        return [None]
    seeds: list[int | None] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        seeds.append(int(part))
    return seeds or [None]


def aggregate_scores(scores: list[float], metric: str, mode: str) -> tuple[float, dict[str, Any]]:
    if not scores:
        raise ValueError("cannot aggregate an empty score list")
    if len(scores) == 1:
        return scores[0], {
            "aggregation": "single",
            "n": 1,
            "scores": scores,
        }

    mean = statistics.mean(scores)
    std = statistics.stdev(scores)
    stderr = std / (len(scores) ** 0.5)
    mode = mode if mode in {"mean", "median", "conservative"} else "conservative"
    if mode == "mean":
        aggregate = mean
    elif mode == "median":
        aggregate = statistics.median(scores)
    else:
        # Penalize variance during search. For minimization, lower is better,
        # so use an upper confidence-ish bound; for maximization, use a lower
        # bound. Final claims still go through optimize:verify.
        aggregate = mean + stderr if metric == "min" else mean - stderr
    return aggregate, {
        "aggregation": mode,
        "n": len(scores),
        "scores": scores,
        "mean": mean,
        "std": std,
        "stderr": stderr,
    }


def build_scorecard(metric: str, score: float, parsed: dict[str, Any]) -> dict[str, Any] | None:
    examples = parsed.get("examples") or []
    items = []
    for i, ex in enumerate(examples[:200]):
        if not isinstance(ex, dict):
            continue
        item: dict[str, Any] = {
            "ref": str(ex.get("id", f"ex_{i}")),
            "score": ex.get("score"),
            "pass": bool(ex.get("pass", (ex.get("score") or 0) > 0)),
        }
        if ex.get("feedback"):
            item["feedback"] = str(ex["feedback"])[:500]
        items.append(item)
    if not items:
        return None
    return {
        "spec": "evaluation_v1",
        "metric": metric,
        "items": items,
        "aggregate": {"score": score, "n": len(items), "passed": sum(1 for i_ in items if i_["pass"])},
    }


def build_repetition_scorecard(metric: str, aggregate_score: float, reps: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for i, rep in enumerate(reps[:200]):
        score = rep.get("score")
        items.append({
            "ref": f"seed_{rep.get('seed', i)}",
            "score": score,
            "pass": isinstance(score, (int, float)),
            "feedback": str(rep.get("feedback", ""))[:500],
        })
    return {
        "spec": "evaluation_v1",
        "metric": metric,
        "items": items,
        "aggregate": {
            "score": aggregate_score,
            "n": len(items),
            "passed": sum(1 for item in items if item["pass"]),
        },
    }


def feedback_digest(parsed: dict[str, Any], stderr: str) -> str:
    """Compact per-example feedback for GEPA's reflector (the ARC lesson:
    the metric doubles as the feedback channel)."""
    lines: list[str] = []
    for ex in (parsed.get("examples") or [])[:12]:
        if isinstance(ex, dict) and ex.get("feedback"):
            lines.append(f"[{ex.get('id', '?')}] {ex['feedback']}")
    if not lines and stderr.strip():
        lines.append(stderr.strip()[-1500:])
    return "\n".join(lines)[:4000]


def repeated_feedback_digest(reps: list[dict[str, Any]], aggregate: dict[str, Any]) -> str:
    lines = [
        "Search-time repeated scoring:",
        f"- aggregation: {aggregate.get('aggregation')}",
        f"- aggregate_score: {aggregate.get('score')}",
        f"- mean: {aggregate.get('mean', aggregate.get('score'))}",
        f"- std: {aggregate.get('std', '-')}",
        f"- stderr: {aggregate.get('stderr', '-')}",
        f"- raw_scores: {aggregate.get('scores')}",
        "",
    ]
    for rep in reps[:6]:
        lines.append(f"[seed {rep.get('seed')}] score={rep.get('score')}")
        feedback = str(rep.get("feedback") or "").strip()
        if feedback:
            lines.append(feedback[:900])
        lines.append("")
    return "\n".join(lines)[:4000]


# --------------------------------------------------------------------------- #
# evaluator
# --------------------------------------------------------------------------- #
class WorktreeEvaluator:
    """GEPA evaluator: isolated worktree -> benchmark -> gates -> score.

    Persistence split: successful evaluations file their extras (commit sha,
    stdout, scorecard) into the registry for AtlasCallback to merge when it
    records the candidate node off the valset event; hard failures (crash /
    timeout / gate) never reach a valset event, so they are recorded as
    failed run nodes directly from here.
    """

    def __init__(self, *, root: Path, target_rel: str, benchmark: str, metric: str,
                 objective: str, gates: list[str], registry: EvaluatorRegistry,
                 callback: AtlasCallback, run_id: str, timeout: int,
                 search_seeds: list[int | None], search_aggregation: str) -> None:
        self.root = root
        self.target_rel = target_rel
        self.benchmark = benchmark
        self.metric = metric
        self.objective = objective
        self.gates = gates
        self.registry = registry
        self.callback = callback
        self.run_id = run_id
        self.timeout = timeout
        self.search_seeds = search_seeds
        self.search_aggregation = search_aggregation
        self.n = 0
        self.repo_url = remote_url(root)
        self._lock = threading.Lock()  # evaluate() runs concurrently under --parallel

    def evaluate(self, candidate: Any, example: Any = None) -> tuple[float, dict[str, Any]]:
        with self._lock:
            self.n += 1
            n = self.n
        if isinstance(candidate, str):
            candidate = {self.target_rel: candidate}
        elif isinstance(candidate, dict) and "current_candidate" in candidate and self.target_rel not in candidate:
            candidate = {self.target_rel: candidate["current_candidate"]}

        wt = self.root / ".atlas-optimize" / "worktrees" / uuid.uuid4().hex[:12]
        side: dict[str, Any] = {"candidate_index": n}
        try:
            add_worktree(self.root, wt)
            for rel, contents in candidate.items():
                dest = wt / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(str(contents), encoding="utf-8")

            target_abs = wt / self.target_rel
            result_file = wt / ".atlas-optimize-result.json"
            env = os.environ.copy()
            env["ATLAS_OPTIMIZE_TARGET"] = str(target_abs)
            env["ATLAS_OPTIMIZE_RESULT"] = str(result_file)
            cmd = self.benchmark.replace("{target}", str(target_abs)).replace("{worktree}", str(wt))

            reps: list[dict[str, Any]] = []
            stdout_chunks: list[str] = []
            stderr_chunks: list[str] = []
            for seed in self.search_seeds:
                rep_env = env.copy()
                if seed is not None:
                    rep_env["ATLAS_EVAL_SEED"] = str(seed)
                result_file.unlink(missing_ok=True)
                rep_label = "default" if seed is None else str(seed)
                try:
                    proc = subprocess.run(cmd, cwd=wt, shell=True, env=rep_env,
                                          capture_output=True, text=True, timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    side["seed"] = rep_label
                    return self._record_failure(candidate, side, f"benchmark_timeout_seed_{rep_label}", "other")

                stdout_chunks.append(f"=== seed {rep_label} stdout ===\n{proc.stdout or ''}")
                stderr_chunks.append(f"=== seed {rep_label} stderr ===\n{proc.stderr or ''}")
                side["stdout"] = "\n".join(stdout_chunks)[-3000:]
                side["stderr"] = "\n".join(stderr_chunks)[-3000:]
                if proc.returncode != 0:
                    return self._record_failure(
                        candidate, side, f"benchmark_exit_{proc.returncode}_seed_{rep_label}", "code_bug"
                    )

                try:
                    rep_score, parsed = read_result(result_file, proc.stdout)
                except (ValueError, json.JSONDecodeError) as exc:
                    return self._record_failure(candidate, side, f"bad_result_seed_{rep_label}: {exc}", "code_bug")

                # Gates: protected behaviors that must hold regardless of score
                # (the Goodhart guard). Exit 0 = pass.
                failed_gates = []
                for gate in self.gates:
                    gate_cmd = gate.replace("{target}", str(target_abs)).replace("{worktree}", str(wt))
                    try:
                        g = subprocess.run(gate_cmd, cwd=wt, shell=True, env=rep_env,
                                           capture_output=True, text=True, timeout=self.timeout)
                        if g.returncode != 0:
                            failed_gates.append(gate)
                    except subprocess.TimeoutExpired:
                        failed_gates.append(f"{gate} (timeout)")
                if failed_gates:
                    side["gate_failures"] = failed_gates
                    return self._record_failure(
                        candidate, side, f"gate failed seed {rep_label}: {'; '.join(failed_gates)[:300]}",
                        "other", score=rep_score,
                    )
                reps.append({
                    "seed": rep_label,
                    "score": rep_score,
                    "metrics": parsed.get("metrics"),
                    "feedback": feedback_digest(parsed, proc.stderr or ""),
                    "parsed": parsed,
                })

            scores = [float(rep["score"]) for rep in reps]
            score, aggregate = aggregate_scores(scores, self.metric, self.search_aggregation)
            aggregate["score"] = score

            sha = commit_candidate(self.root, wt, self.run_id, n)
        finally:
            remove_worktree(self.root, wt)

        side["benchmark_result"] = {
            "score": score,
            "search_aggregate": aggregate,
            "search_repetitions": [
                {k: v for k, v in rep.items() if k != "parsed"} for rep in reps
            ],
        }
        side["feedback"] = (
            repeated_feedback_digest(reps, aggregate)
            if len(reps) > 1
            else reps[0].get("feedback", "")
        )

        # File extras for AtlasCallback to merge into the candidate node.
        scorecard = (
            build_repetition_scorecard(self.metric, score, reps)
            if len(reps) > 1
            else build_scorecard(self.metric, score, reps[0]["parsed"])
        )
        extras: dict[str, Any] = {
            "stdout_tail": side.get("stdout"),
            "scorecard": scorecard,
            "config": {
                "candidate_chars": sum(len(str(v)) for v in candidate.values()),
                "search_seeds": [rep["seed"] for rep in reps],
                "search_aggregation": aggregate.get("aggregation"),
                "raw_benchmark_calls": len(reps),
            },
            "metrics": {
                "score": score,
                "search": aggregate,
            },
        }
        if sha:
            extras.update(
                head_commit_sha=sha,
                branch_name=f"refs/atlas/optimize/{self.run_id}/cand-{n}",
            )
            if self.repo_url:
                extras["repo_url"] = self.repo_url

        if self.callback.engine_events_supported:
            self.registry.put(candidate, extras)
        else:
            # Compat mode (gepa without engine callbacks): record from here.
            self.callback.record_evaluation(
                candidate, score, extras.get("scorecard"), extras
            )

        return (-score if self.metric == "min" else score), side

    def _record_failure(self, candidate: dict[str, Any], side: dict[str, Any],
                        error: str, failure_mode: str, score: float | None = None) -> tuple[float, dict[str, Any]]:
        side["error"] = error
        if self.callback.control:
            body = {
                "project_id": self.callback.control,
                "title": f"candidate (eval {side.get('candidate_index', '?')}) · FAILED",
                "outcome": "failure",
                "failure_mode": failure_mode,
                "stdout_tail": ((side.get("stdout") or "") + "\n" + (side.get("stderr") or "")).strip()[-3000:],
                "metrics": {"score": score} if score is not None else None,
            }
            body = {k: v for k, v in body.items() if v is not None}
            try:
                atlas_json(["run:record", "--no-git", "--payload-json", json.dumps(body)])
            except Exception as exc:  # noqa: BLE001
                print(f"[optimize] failure record failed: {exc}", file=sys.stderr)
        return GEPA_WORST, side


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def run(args: argparse.Namespace) -> int:
    if not os.environ.get("ATLAS_API_KEY"):
        print("error: ATLAS_API_KEY is not set", file=sys.stderr)
        return 2

    root = repo_root()
    target = Path(args.target)
    if not (root / target).exists():
        print(f"error: target not found: {target}", file=sys.stderr)
        return 2
    seed_text = (root / target).read_text(encoding="utf-8")
    target_rel = str(target)
    run_id = time.strftime("%Y%m%d-%H%M%S")
    run_dir = Path(args.run_dir or (root / ".atlas-optimize" / f"run-{run_id}"))
    run_dir.mkdir(parents=True, exist_ok=True)
    stop_file = run_dir / "gepa.stop"
    stop_file.unlink(missing_ok=True)  # a stale stop file must not kill a fresh run

    # Resume continues the SEARCH, not just the control node: seed from the
    # best recorded candidate's exact content (its commit), falling back to
    # the on-disk target when the map has no usable best yet.
    if args.resume:
        resumed = best_candidate_seed(args.resume, target_rel, root)
        if resumed:
            seed_text, best_node = resumed
            print(f"[optimize] resuming from best candidate {best_node}")
        else:
            print(f"[optimize] no recorded best candidate found — seeding from {target_rel}")

    registry = EvaluatorRegistry()
    callback = AtlasCallback(
        label=args.run_label or target.name,
        objective=args.objective,
        metric=args.metric,
        target=target_rel,
        project=args.project,
        control=args.resume,
        registry=registry,
        run_dir=str(run_dir.relative_to(root) if run_dir.is_relative_to(root) else run_dir),
    )
    control = callback.ensure_control()
    if not control:
        print("error: could not create/reach the control node", file=sys.stderr)
        return 2
    callback.budget_total = args.max_metric_calls
    callback.progress(
        budget_total=args.max_metric_calls,
        stall_limit=args.stall,
        run_dir=callback.run_dir,
    )

    evaluator = WorktreeEvaluator(
        root=root, target_rel=target_rel, benchmark=args.benchmark, metric=args.metric,
        objective=args.objective, gates=args.gate or [], registry=registry,
        callback=callback, run_id=run_id, timeout=args.benchmark_timeout,
        search_seeds=parse_search_seeds(args.search_seeds),
        search_aggregation=args.search_aggregation,
    )

    # Imported lazily so --help works without gepa installed.
    import dataclasses

    from gepa.optimize_anything import EngineConfig, GEPAConfig, ReflectionConfig, optimize_anything
    from gepa.utils.stop_condition import CompositeStopper, MaxMetricCallsStopper, NoImprovementStopper

    try:  # FileStopper shipped in gepa 0.1.1; keep a fallback for older installs
        from gepa.utils.stop_condition import FileStopper
    except ImportError:
        class FileStopper:  # type: ignore[no-redef]
            def __init__(self, stop_file_path: str) -> None:
                self.stop_file_path = stop_file_path

            def __call__(self, gepa_state: Any) -> bool:
                return os.path.exists(self.stop_file_path)

    reflection_kwargs: dict[str, Any] = {}
    if args.reflection_lm:
        reflection_kwargs["reflection_lm"] = args.reflection_lm
    if args.ground:
        proposer = GroundedProposer(
            objective=args.objective,
            reflection_lm=args.reflection_lm,
            callback=callback,
            stall_after=min(max(2, args.stall - 1), 6),
            consult_every=max(0, args.ground_every),
            max_consults=args.ground_max if args.ground_max > 0 else 3,
        )
        if args.require_grounding:
            try:
                proposer.preflight()
                print("[optimize] grounding preflight: ok")
            except Exception as exc:  # noqa: BLE001
                print(f"error: {exc}", file=sys.stderr)
                callback.finish("runtime_error", status="error")
                return 2
        reflection_kwargs["custom_candidate_proposer"] = proposer
        cadence = f", every {args.ground_every} evals" if args.ground_every else ""
        print(f"[optimize] web-grounded reflection: on (stall trigger{cadence})")

    parallel = max(1, int(args.parallel or 1))
    engine_fields = {f.name for f in dataclasses.fields(EngineConfig)}
    engine_kwargs: dict[str, Any] = {
        "max_metric_calls": args.max_metric_calls,
        "display_progress_bar": False,
        "parallel": parallel > 1,
        "run_dir": str(run_dir),
    }
    if parallel > 1:
        if "max_workers" in engine_fields:
            engine_kwargs["max_workers"] = parallel
        # Single-task search evaluates one example per candidate, so true
        # concurrency comes from parallel proposal pipelines (K candidates
        # evaluated at once), not batch-level workers.
        if "num_parallel_proposals" in engine_fields:
            engine_kwargs["num_parallel_proposals"] = parallel
            print(f"[optimize] parallel evaluation: {parallel} concurrent proposals")
        else:
            print(
                "[optimize] installed gepa has no num_parallel_proposals — running serial. "
                "`atlas optimize:start --parallel K` pins a gepa build that supports it.",
                file=sys.stderr,
            )

    stoppers: list[Any] = [
        MaxMetricCallsStopper(max_metric_calls=args.max_metric_calls),
        NoImprovementStopper(max_iterations_without_improvement=args.stall),
        FileStopper(str(stop_file)),  # `atlas optimize:stop` writes this mid-run
    ]
    if args.max_seconds and args.max_seconds > 0:
        # gepa ships TimeoutStopCondition (wall-clock); prefer it, fall back to
        # the built-in DeadlineStopper if the symbol moved or signature differs.
        try:
            from gepa.utils.stop_condition import TimeoutStopCondition
            stoppers.append(TimeoutStopCondition(timeout_seconds=float(args.max_seconds)))
        except Exception:  # noqa: BLE001
            stoppers.append(DeadlineStopper(args.max_seconds))
        print(f"[optimize] wall-clock budget: {args.max_seconds}s")
    config_kwargs: dict[str, Any] = {
        "engine": EngineConfig(**engine_kwargs),
        "reflection": ReflectionConfig(**reflection_kwargs),
        "stop_callbacks": CompositeStopper(*stoppers),
    }
    # Engine callbacks landed in gepa after the current PyPI release. With a
    # callback-aware gepa we get exact lineage from engine events; otherwise
    # the evaluator drives recording ("compat mode": best-so-far lineage).
    gepa_has_callbacks = "callbacks" in {f.name for f in dataclasses.fields(GEPAConfig)}
    callback.engine_events_supported = gepa_has_callbacks
    # Engine events carry GEPA-space scores; min metrics are negated for GEPA,
    # so the callback must un-negate them back to true benchmark space.
    callback.negate_engine_scores = gepa_has_callbacks and args.metric == "min"
    if gepa_has_callbacks:
        config_kwargs["callbacks"] = [callback]
    else:
        print("[optimize] installed gepa predates engine callbacks — evaluator-driven recording")
    config = GEPAConfig(**config_kwargs)

    status = "done"
    started_at = time.time()
    try:
        result = optimize_anything(
            seed_candidate={target_rel: seed_text},
            evaluator=evaluator.evaluate,
            objective=args.objective,
            background=args.background,
            config=config,
        )
        used = getattr(result, "total_metric_calls", None) or evaluator.n
        callback.budget_used = max(callback.budget_used, int(used))
        if (run_dir / "gepa.stop").exists():
            stop_reason = "user_cancelled"
            status = "stopped"
        elif args.max_seconds and (time.time() - started_at) >= args.max_seconds:
            stop_reason = "budget_exhausted"  # wall-clock budget hit
        elif used >= args.max_metric_calls:
            stop_reason = "budget_exhausted"
        else:
            stop_reason = "no_improvement"
    except KeyboardInterrupt:
        stop_reason, status = "user_cancelled", "stopped"
    except Exception as exc:  # noqa: BLE001
        print(f"optimize error: {exc}", file=sys.stderr)
        stop_reason, status = "runtime_error", "error"

    callback.finish(stop_reason, status=status)

    # Machine-readable result contract: lets a wrapper (e.g. `atlas
    # autoresearch`) learn the control node + winner without scraping stdout.
    try:
        (run_dir / "optimize-result.json").write_text(
            json.dumps({
                "control_node_id": control,
                "best_node_id": callback.best[1] if callback.best else None,
                "best_score": callback.best[0] if callback.best else None,
                "stop_reason": stop_reason,
                "status": status,
                "evaluations": evaluator.n,
                "candidates_recorded": callback.candidates_recorded,
                "target": target_rel,
                "metric": args.metric,
            }),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[optimize] result-contract write failed: {exc}", file=sys.stderr)

    best = f"{callback.best[1]} (score {callback.best[0]:g})" if callback.best else "none"
    print(
        f"done · stop_reason={stop_reason} · evaluations={evaluator.n} · "
        f"candidates_recorded={callback.candidates_recorded} · best={best}\n"
        f"inspect: atlas optimize:status --node {control} · "
        f"atlas leaderboard --project {control} --metric metrics.score"
    )
    return 1 if status == "error" else 0


def main() -> int:
    p = argparse.ArgumentParser(description="Run GEPA optimize_anything into the Gateway map.")
    p.add_argument("--target", required=True, help="repo-relative path to the artifact GEPA mutates")
    p.add_argument("--benchmark", required=True, help="shell command; {target}/{worktree} are substituted")
    p.add_argument("--metric", choices=["max", "min"], default="max")
    p.add_argument("--objective", required=True, help="one sentence: what 'better' means")
    p.add_argument("--background", default=None, help="optional extra context for GEPA's reflector")
    p.add_argument("--max-metric-calls", type=int, default=50, dest="max_metric_calls")
    p.add_argument("--max-seconds", type=int, default=0, dest="max_seconds",
                   help="wall-clock budget in seconds; stop at the next iteration boundary past the "
                        "deadline (0 = no time limit). Composes with --max-metric-calls (first to hit wins).")
    p.add_argument("--stall", type=int, default=5)
    p.add_argument("--parallel", type=int, default=1,
                   help="concurrent candidate evaluations (parallel proposal pipelines)")
    p.add_argument("--search-seeds", default="", dest="search_seeds",
                   help="comma-separated ATLAS_EVAL_SEED values to repeat per candidate during search")
    p.add_argument("--search-aggregation", default="conservative", dest="search_aggregation",
                   choices=["mean", "median", "conservative"],
                   help="how repeated search scores are collapsed before GEPA sees them")
    p.add_argument("--reflection-lm", default=None, dest="reflection_lm")
    p.add_argument("--run-label", default=None, dest="run_label")
    p.add_argument("--project", default=None, help="parent node for the control node")
    p.add_argument("--resume", default=None, help="existing control node to continue under")
    p.add_argument("--gate", action="append", default=[], help="gate command (repeatable); exit 0 = pass")
    p.add_argument("--ground", action="store_true", default=False,
                   help="web-grounded reflection on stall")
    p.add_argument("--no-ground", dest="ground", action="store_false")
    p.add_argument("--require-grounding", dest="require_grounding", action="store_true", default=True,
                   help="preflight grounding before spending evaluation budget (default)")
    p.add_argument("--no-require-grounding", dest="require_grounding", action="store_false",
                   help="skip grounding preflight; consult failures become warnings")
    p.add_argument("--ground-every", type=int, default=0, dest="ground_every",
                   help="also consult web search every N scored evals (0 = stall-only)")
    p.add_argument("--ground-max", type=int, default=3, dest="ground_max",
                   help="max web-search consults per run (default 3)")
    p.add_argument("--run-dir", default=None, dest="run_dir",
                   help="state dir (gepa.stop lives here; default .atlas-optimize/run-<ts>)")
    p.add_argument("--benchmark-timeout", type=int, default=BENCHMARK_TIMEOUT_DEFAULT, dest="benchmark_timeout")
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
