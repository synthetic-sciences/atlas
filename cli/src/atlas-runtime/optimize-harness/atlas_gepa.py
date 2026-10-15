"""Gateway <-> GEPA bridge.

Two integration layers, usable together or alone:

1. ``AtlasCallback`` — a `GEPACallback` observer that streams ANY gepa run
   into the Gateway map: one control node per run (live budget / best-score
   state via ``optimize:progress``), one empirical node per candidate with
   lineage (``parent_run_id``), per-example scorecards (``evaluation_v1``),
   and the reflection prompts/outputs behind each accepted candidate
   attached as evidence. Works with ``gepa.optimize_anything`` and the
   classic ``gepa.optimize`` (DSPy adapter) alike:

       from atlas_gepa import AtlasCallback
       cb = AtlasCallback(label="arc-agi", objective="...", metric="max")
       optimize_anything(..., config=GEPAConfig(callbacks=[cb], ...))

2. ``GroundedProposer`` — a `ProposalFn` that wraps GEPA's reflection step
   with Gateway web grounding: when the search stalls, it digests the
   dominant failures, retrieves bounded web-search snippets
   (``atlas web:search``), and folds those snippets into the reflection
   prompt. Each consult is recorded as an insight node under
   the control node, so the map shows *why* the optimizer changed course.

Both layers persist through the ``atlas`` CLI (auth, spool, scrubbing for
free). Callback handlers never raise — a persistence hiccup must not kill
an optimization run.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

# --------------------------------------------------------------------------- #
# Gateway CLI plumbing
# --------------------------------------------------------------------------- #

def _cli_argv() -> list[str]:
    override = os.environ.get("ATLAS_CLI")
    if override:
        return shlex.split(override)
    found = shutil.which("atlas")
    if not found:
        raise RuntimeError("`atlas` CLI not found on PATH (set ATLAS_CLI to override)")
    return [found]


def atlas_json(args: list[str], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run an ``atlas`` command with --format=json and return the parsed result."""
    cmd = [*_cli_argv(), *args, "--format=json"]
    tmp_path: Path | None = None
    if payload is not None:
        fd, name = tempfile.mkstemp(suffix=".json")
        tmp_path = Path(name)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        cmd += ["--payload-json", f"@{tmp_path}"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"`atlas {' '.join(args)}` failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    out = proc.stdout.strip()
    try:
        return json.loads(out) if out else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"`atlas {' '.join(args)}` did not return JSON: {out[:200]!r}") from exc


def node_id_of(result: dict[str, Any]) -> str:
    for candidate in (result, result.get("node"), result.get("data")):
        if isinstance(candidate, dict) and candidate.get("node_id"):
            return str(candidate["node_id"])
    raise RuntimeError(f"could not find node_id in CLI response: {result!r}")


def _warn(message: str) -> None:
    print(f"[atlas-gepa] {message}", file=sys.stderr)


def candidate_fingerprint(candidate: Any) -> str:
    try:
        canonical = json.dumps(candidate, sort_keys=True, default=str)
    except TypeError:
        canonical = repr(candidate)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


class EvaluatorRegistry:
    """Shared scratch between an evaluator and the callback.

    The evaluator knows things events don't carry (commit shas, stdout,
    gate failures, per-example feedback); it files them here keyed by the
    candidate's content fingerprint, and the callback merges them into the
    recorded node.
    """

    def __init__(self) -> None:
        self._extras: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def put(self, candidate: Any, extras: dict[str, Any]) -> None:
        with self._lock:
            self._extras[candidate_fingerprint(candidate)] = extras

    def pop(self, candidate: Any) -> dict[str, Any]:
        with self._lock:
            return self._extras.pop(candidate_fingerprint(candidate), {})


# --------------------------------------------------------------------------- #
# AtlasCallback
# --------------------------------------------------------------------------- #

class AtlasCallback:
    """GEPACallback that persists the run into the Gateway map.

    Parameters:
        label:       human title for the control node.
        objective:   one sentence; shown on the control node + cards.
        metric:      "max" | "min" (chart + best-so-far direction).
        target:      optional artifact path (contract field).
        project:     optional parent node id/slug for the control node.
        control:     reuse an existing control node id (resume).
        registry:    optional EvaluatorRegistry for harness pairing.
        run_dir:     local dir recorded on the control node (optimize:stop).
        auto_chart:  attach a score-progression chart on completion.
    """

    def __init__(
        self,
        *,
        label: str | None = None,
        objective: str | None = None,
        metric: str = "max",
        target: str | None = None,
        project: str | None = None,
        control: str | None = None,
        registry: EvaluatorRegistry | None = None,
        run_dir: str | None = None,
        auto_chart: bool = True,
        record_proposals: bool = True,
    ) -> None:
        self.label = label or "optimize run"
        self.objective = objective
        self.metric = "min" if metric == "min" else "max"
        self.target = target
        self.project = project
        self.control = control
        self.registry = registry
        self.run_dir = run_dir
        self.auto_chart = auto_chart
        self.record_proposals = record_proposals

        self.idx_to_node: dict[int, str] = {}
        self.best: tuple[float, str] | None = None  # (score, node_id) in TRUE benchmark space
        self.candidates_recorded = 0
        self.budget_total: int | None = None
        self.budget_used = 0
        # min-metric harnesses negate scores so GEPA can maximize; engine
        # events then carry GEPA-space values. When set, event scores are
        # un-negated back to true benchmark space before recording/comparing.
        # (Compat-mode record_evaluation() already receives true-space scores.)
        self.negate_engine_scores = False
        # Recording serializes under one lock: handlers fire from concurrent
        # proposal threads under --parallel, and persistence calls are cheap
        # relative to benchmark runs.
        self._record_lock = threading.RLock()
        self._last_proposal: dict[str, Any] | None = None
        self._pending_proposal_for: dict[int, dict[str, Any]] = {}
        self.grounding_hook: Callable[[float], None] | None = None
        # Released gepa builds (<= 0.x on PyPI) don't accept callbacks on
        # GEPAConfig yet; in that "compat mode" the evaluator drives
        # recording via record_evaluation() instead of engine events.
        self.engine_events_supported = True
        self._compat_parent: str | None = None
        # Proposals keyed by the fingerprint of the proposed candidate, so
        # compat mode can attach reflection provenance without engine events.
        self.pending_proposals: dict[str, dict[str, Any]] = {}

    # -- control node ------------------------------------------------------

    def ensure_control(self) -> str | None:
        if self.control:
            return self.control
        try:
            envelope = {
                "local_temp_node_id": f"opt-{uuid.uuid4().hex[:12]}",
                "parent_ids": [self.project] if self.project else [],
                "staged_payload": {
                    "title": f"optimize: {self.label}",
                    "summary": self.objective or f"GEPA optimize run · {self.label}",
                    "content": (
                        "## Optimize run\n\n"
                        f"- Objective: {self.objective or '-'}\n"
                        f"- Target: {self.target or '-'}\n"
                        f"- Metric: {self.metric}\n\n"
                        "Live state (budget, best, stop reason) is on this node's "
                        "optimization panel; candidates are the child runs.\n"
                    ),
                    "kind": "insight",
                    "insights": [f"GEPA optimize run: {self.label}"],
                    "outcome": "completed",
                },
            }
            self.control = node_id_of(atlas_json(["node:create"], envelope))
            self.progress(
                status="running",
                objective=self.objective,
                target=self.target,
                metric=self.metric,
                run_dir=self.run_dir,
            )
            print(f"[atlas-gepa] control node: {self.control}")
        except Exception as exc:  # noqa: BLE001
            _warn(f"control node creation failed: {exc}")
        return self.control

    def progress(self, **fields: Any) -> None:
        if not self.control:
            return
        args = ["optimize:progress", "--node-id", self.control]
        sent = False
        for key, value in fields.items():
            if value is None:
                continue
            args += [f"--{key.replace('_', '-')}", str(value)]
            sent = True
        if not sent:
            return
        try:
            atlas_json(args)
        except Exception as exc:  # noqa: BLE001
            _warn(f"optimize:progress failed: {exc}")

    # -- scorecards ---------------------------------------------------------

    @staticmethod
    def _scorecard_from_valset(event: dict[str, Any]) -> dict[str, Any] | None:
        scores = event.get("scores_by_val_id")
        if not isinstance(scores, dict) or not scores:
            return None
        items = [
            {"ref": str(ref)[:120], "score": float(score), "pass": float(score) > 0}
            for ref, score in list(scores.items())[:200]
            if isinstance(score, (int, float))
        ]
        if not items:
            return None
        return {
            "spec": "evaluation_v1",
            "metric": "score",
            "items": items,
            "aggregate": {
                "score": event.get("average_score"),
                "n": len(items),
                "passed": sum(1 for item in items if item["pass"]),
            },
        }

    # -- candidate recording -------------------------------------------------

    def _record_candidate(
        self,
        candidate_idx: int,
        candidate: dict[str, str] | None,
        average_score: float | None,
        scorecard: dict[str, Any] | None,
        parent_ids: Any,
        is_best: bool,
    ) -> None:
        with self._record_lock:
            self._record_candidate_inner(
                candidate_idx, candidate, average_score, scorecard, parent_ids, is_best
            )

    def _true_score(self, event_score: float) -> float:
        """Engine events carry GEPA-space scores (negated for min metrics);
        convert back to true benchmark space for recording and comparison."""
        return -event_score if self.negate_engine_scores else event_score

    def _record_candidate_inner(
        self,
        candidate_idx: int,
        candidate: dict[str, str] | None,
        average_score: float | None,
        scorecard: dict[str, Any] | None,
        parent_ids: Any,
        is_best: bool,
    ) -> None:
        if not self.control or candidate_idx in self.idx_to_node:
            return
        extras = self.registry.pop(candidate) if (self.registry and candidate is not None) else {}
        parent_node = None
        for pid in parent_ids or []:
            if isinstance(pid, int) and pid in self.idx_to_node:
                parent_node = self.idx_to_node[pid]
                break

        score = (
            self._true_score(float(average_score))
            if isinstance(average_score, (int, float)) else None
        )
        # Failure sentinels (the harness hands GEPA ±1e12 for crashed/gated
        # candidates) are not scores; the evaluator already recorded the real
        # failure node with its failure_mode and log tail. Don't duplicate it
        # as a "completed" candidate with an absurd metric.
        if score is not None and abs(score) >= 1e11:
            return
        if scorecard and self.negate_engine_scores:
            scorecard = json.loads(json.dumps(scorecard))  # don't mutate the event
            for item in scorecard.get("items", []):
                if isinstance(item.get("score"), (int, float)):
                    item["score"] = -item["score"]
            agg = scorecard.get("aggregate") or {}
            if isinstance(agg.get("score"), (int, float)):
                agg["score"] = -agg["score"]

        metrics = {"score": score} if score is not None else {}
        extra_metrics = extras.get("metrics")
        if isinstance(extra_metrics, dict):
            metrics.update(extra_metrics)
        body: dict[str, Any] = {
            "project_id": self.control,
            "title": f"candidate {candidate_idx}"
            + (f" · {score:g}" if score is not None else ""),
            "outcome": "success",
            "candidate_idx": candidate_idx,
            "metrics": metrics or None,
            "scorecard": extras.get("scorecard") or scorecard,
            "parent_run_id": parent_node,
            "stdout_tail": extras.get("stdout_tail"),
            "config": extras.get("config"),
            "repo_url": extras.get("repo_url"),
            "branch_name": extras.get("branch_name"),
            "head_commit_sha": extras.get("head_commit_sha"),
        }
        body = {k: v for k, v in body.items() if v is not None}
        try:
            args = ["run:record", "--payload-json", json.dumps(body)]
            if not extras.get("head_commit_sha"):
                args.append("--no-git")
            result = atlas_json(args)
            node = node_id_of(result)
            self.idx_to_node[candidate_idx] = node
            self.candidates_recorded += 1
            if score is not None:
                better = (
                    self.best is None
                    or (self.metric == "max" and score > self.best[0])
                    or (self.metric == "min" and score < self.best[0])
                )
                if better:
                    self.best = (float(score), node)
            self.progress(
                candidates_evaluated=self.candidates_recorded,
                best_score=self.best[0] if (self.best and is_best) else None,
                best_node_id=self.best[1] if (self.best and is_best) else None,
            )
            pending = self._pending_proposal_for.pop(candidate_idx, None)
            if pending:
                self._attach_proposal(node, pending)
        except Exception as exc:  # noqa: BLE001
            _warn(f"candidate record failed: {exc}")

    def record_evaluation(
        self,
        candidate: Any,
        score: float,
        scorecard: dict[str, Any] | None,
        extras: dict[str, Any] | None = None,
    ) -> str | None:
        """Compat-mode recording: called by the evaluator when the installed
        gepa can't deliver engine callbacks. Lineage approximates GEPA's
        parent selection with best-so-far (a hill-climb chain), which is
        honest enough for the map and infinitely better than a flat star.
        """
        with self._record_lock:
            return self._record_evaluation_inner(candidate, score, scorecard, extras)

    def _record_evaluation_inner(
        self,
        candidate: Any,
        score: float,
        scorecard: dict[str, Any] | None,
        extras: dict[str, Any] | None = None,
    ) -> str | None:
        if not self.control:
            return None
        extras = extras or {}
        self.budget_used += 1
        n = self.candidates_recorded + 1
        metrics = {"score": score}
        extra_metrics = extras.get("metrics")
        if isinstance(extra_metrics, dict):
            metrics.update(extra_metrics)
        body: dict[str, Any] = {
            "project_id": self.control,
            "title": f"candidate {n} · {score:g}",
            "outcome": "success",
            "candidate_idx": n,
            "metrics": metrics,
            "scorecard": extras.get("scorecard") or scorecard,
            "parent_run_id": self._compat_parent,
            "stdout_tail": extras.get("stdout_tail"),
            "config": extras.get("config"),
            "repo_url": extras.get("repo_url"),
            "branch_name": extras.get("branch_name"),
            "head_commit_sha": extras.get("head_commit_sha"),
        }
        body = {k: v for k, v in body.items() if v is not None}
        try:
            args = ["run:record", "--payload-json", json.dumps(body)]
            if not extras.get("head_commit_sha"):
                args.append("--no-git")
            node = node_id_of(atlas_json(args))
        except Exception as exc:  # noqa: BLE001
            _warn(f"candidate record failed: {exc}")
            return None
        self.candidates_recorded += 1
        better = (
            self.best is None
            or (self.metric == "max" and score > self.best[0])
            or (self.metric == "min" and score < self.best[0])
        )
        if better:
            self.best = (float(score), node)
            self._compat_parent = node
        elif self._compat_parent is None:
            self._compat_parent = node
        self.progress(
            budget_used=self.budget_used,
            candidates_evaluated=self.candidates_recorded,
            best_score=self.best[0] if better and self.best else None,
            best_node_id=self.best[1] if better and self.best else None,
        )
        proposal = self.pending_proposals.pop(candidate_fingerprint(candidate), None)
        if proposal:
            self._attach_proposal(node, proposal)
        if self.grounding_hook:
            # The hook expects higher-is-better (GEPA-space) values.
            self.grounding_hook(-float(score) if self.metric == "min" else float(score))
        return node

    def _attach_proposal(self, node_id: str, proposal: dict[str, Any]) -> None:
        """Reflection provenance: the prompt + raw LM output that produced
        this candidate, attached as a JSON evidence artifact."""
        if not self.record_proposals:
            return
        try:
            node = atlas_json(["node:show", "--node", node_id])
            revision = (node.get("node") or node).get("revision")
            fd, name = tempfile.mkstemp(prefix="reflection-", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(proposal, fh, indent=2, default=str)
            atlas_json(
                [
                    "evidence:add",
                    "--node", node_id,
                    "--expected-revision", str(revision),
                    "--items", json.dumps(
                        [{
                            "local_path": name,
                            "artifact_type": "json",
                            "title": "reflection that produced this candidate",
                        }]
                    ),
                ]
            )
            Path(name).unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            _warn(f"proposal evidence attach failed: {exc}")

    # -- GEPACallback protocol ------------------------------------------------

    def on_optimization_start(self, event: dict[str, Any]) -> None:
        try:
            self.ensure_control()
            config = event.get("config") or {}
            budget = None
            engine = config.get("engine") if isinstance(config, dict) else None
            if isinstance(engine, dict):
                budget = engine.get("max_metric_calls")
            budget = budget or (config.get("max_metric_calls") if isinstance(config, dict) else None)
            if budget:
                self.budget_total = int(budget)
            self.progress(status="running", budget_total=self.budget_total)
        except Exception as exc:  # noqa: BLE001
            _warn(f"on_optimization_start failed: {exc}")

    def on_valset_evaluated(self, event: dict[str, Any]) -> None:
        try:
            idx = event.get("candidate_idx")
            if not isinstance(idx, int):
                return
            average = event.get("average_score")
            self._record_candidate(
                candidate_idx=idx,
                candidate=event.get("candidate"),
                average_score=average if isinstance(average, (int, float)) else None,
                scorecard=self._scorecard_from_valset(event),
                parent_ids=event.get("parent_ids"),
                is_best=bool(event.get("is_best_program")),
            )
            if self.grounding_hook and isinstance(average, (int, float)):
                self.grounding_hook(float(average))
        except Exception as exc:  # noqa: BLE001
            _warn(f"on_valset_evaluated failed: {exc}")

    def on_proposal_end(self, event: dict[str, Any]) -> None:
        try:
            self._last_proposal = {
                "iteration": event.get("iteration"),
                "prompts": event.get("prompts"),
                "raw_lm_outputs": event.get("raw_lm_outputs"),
            }
        except Exception:  # noqa: BLE001
            pass

    def on_candidate_accepted(self, event: dict[str, Any]) -> None:
        try:
            idx = event.get("new_candidate_idx")
            if not isinstance(idx, int) or self._last_proposal is None:
                return
            proposal, self._last_proposal = self._last_proposal, None
            node = self.idx_to_node.get(idx)
            if node:
                self._attach_proposal(node, proposal)
            else:
                self._pending_proposal_for[idx] = proposal
        except Exception as exc:  # noqa: BLE001
            _warn(f"on_candidate_accepted failed: {exc}")

    def on_budget_updated(self, event: dict[str, Any]) -> None:
        try:
            used = event.get("metric_calls_used")
            if isinstance(used, int):
                self.budget_used = used
                self.progress(budget_used=used)
        except Exception as exc:  # noqa: BLE001
            _warn(f"on_budget_updated failed: {exc}")

    def on_pareto_front_updated(self, event: dict[str, Any]) -> None:
        try:
            front = event.get("new_front")
            if isinstance(front, list):
                self.progress(pareto_size=len(front))
        except Exception as exc:  # noqa: BLE001
            _warn(f"on_pareto_front_updated failed: {exc}")

    def on_optimization_end(self, event: dict[str, Any]) -> None:
        try:
            self.finish("budget_exhausted" if self._budget_spent() else "no_improvement")
        except Exception as exc:  # noqa: BLE001
            _warn(f"on_optimization_end failed: {exc}")

    # -- lifecycle -----------------------------------------------------------

    def _budget_spent(self) -> bool:
        return bool(self.budget_total and self.budget_used >= self.budget_total)

    def finish(self, stop_reason: str, status: str = "done") -> None:
        """Idempotent final state write + chart. Safe to call from the
        harness after optimize_anything returns (overrides the callback's
        own inferred stop_reason when the harness knows better)."""
        self.progress(
            status=status,
            stop_reason=stop_reason,
            budget_used=self.budget_used or None,
            best_score=self.best[0] if self.best else None,
            best_node_id=self.best[1] if self.best else None,
            candidates_evaluated=self.candidates_recorded or None,
        )
        if self.auto_chart and self.control and self.candidates_recorded >= 2:
            try:
                atlas_json(
                    [
                        "run:chart",
                        "--project", self.control,
                        "--metric", "metrics.score",
                        "--direction", self.metric,
                        "--title", f"score progression · {self.label}",
                    ]
                )
            except Exception as exc:  # noqa: BLE001
                _warn(f"run:chart failed: {exc}")


# --------------------------------------------------------------------------- #
# Web-grounded reflection
# --------------------------------------------------------------------------- #

_GROUNDED_PROMPT = """You are improving a candidate artifact inside an optimization loop.

## Objective
{objective}

## Current candidate ({component})
```
{component_text}
```

## Evaluation feedback (recent examples)
{feedback}
{grounded}
## Task
Propose an improved version of the candidate that addresses the feedback.
Return ONLY the complete improved text for `{component}`, inside a single
fenced code block.
"""


class GroundedProposer:
    """A ``ProposalFn`` with bounded Gateway web grounding on stall.

    Drop-in for ``ReflectionConfig.custom_candidate_proposer``. Builds the
    reflection prompt itself (objective + reflective dataset); when the best
    score hasn't improved for ``stall_after`` evaluations, it searches the
    web and prepends the retrieved snippets to the prompt.
    Consults are recorded under the control node.
    """

    def __init__(
        self,
        *,
        objective: str,
        reflection_lm: str | None = None,
        callback: AtlasCallback | None = None,
        stall_after: int = 4,
        max_consults: int = 3,
        feedback_examples: int = 3,
        consult_every: int = 0,
    ) -> None:
        self.objective = objective
        self.reflection_lm = reflection_lm or "openai/gpt-5.1"
        self.callback = callback
        self.stall_after = stall_after
        self.max_consults = max_consults
        self.feedback_examples = feedback_examples
        # Cadence trigger: also consult every N scored evaluations (0 = stall-only).
        # Short campaigns never reach a long stall window; a cadence makes the
        # web route a steady input rather than an emergency brake.
        self.consult_every = max(0, int(consult_every))

        self._best: float | None = None
        self._since_improve = 0
        self._scores_seen = 0
        self._proposals = 0
        self._next_consult_at = self.consult_every or 0
        self._consults = 0
        self._grounded_context: str | None = None
        self._last_feedback_digest = ""
        self._lock = threading.Lock()  # proposers run concurrently under --parallel
        if callback is not None:
            callback.grounding_hook = self.notice_score

    # Wired to AtlasCallback's valset events (always higher-is-better values).
    def notice_score(self, score: float) -> None:
        with self._lock:
            self._scores_seen += 1
            if self._best is None or score > self._best:
                self._best = score
                self._since_improve = 0
            else:
                self._since_improve += 1

    def _stalled(self) -> bool:
        with self._lock:
            if self._consults >= self.max_consults:
                return False
            if self._since_improve >= self.stall_after:
                return True
            # Watermark cadence on PROPOSALS (each __call__ is one reflection
            # round). Valset events only fire for accepted candidates, which
            # is far too sparse a clock; and under --parallel any counter can
            # jump past an exact-modulo boundary between checks.
            ticks = max(self._proposals, self._scores_seen)
            if self.consult_every > 0 and ticks >= self._next_consult_at > 0:
                self._next_consult_at = ticks + self.consult_every
                return True
            return False

    def _consult_web(self) -> str | None:
        with self._lock:
            # Count attempts, not successes: each search costs quota, and a
            # misconfigured corpus shouldn't be retried at every cadence tick.
            self._consults += 1
        digest = self._last_feedback_digest[:1500] or self.objective
        query = (
            f"Optimization objective: {self.objective}. The search has stalled; "
            f"dominant failure feedback: {digest}. What approaches, tricks, or "
            "parameter regimes from credible sources could fix these failures?"
        )
        try:
            result = atlas_json([
                "web:search",
                "--query", query[:600],
                "--num-results", "5",
                "--no-log",
            ])
            hits = result.get("results") or result.get("hits") or []
            passages = [
                "\n".join(
                    str(value).strip()
                    for value in (hit.get("title"), hit.get("url"), hit.get("snippet"))
                    if value
                )[:1200]
                for hit in hits
                if isinstance(hit, dict)
            ]
            answer = "\n\n---\n\n".join(
                passage for passage in passages if passage.strip()
            )
            if not answer:
                raise RuntimeError("search returned no passages")
            self._record_consult(query, str(answer))
            return str(answer)[:4000]
        except Exception as exc:  # noqa: BLE001
            _warn(f"web consult failed: {exc}")
            return None

    def preflight(self) -> None:
        """Fail before GPU spend when the grounding corpus is not reachable."""
        query = (
            "Grounding preflight for a Gateway optimization run. Return one "
            f"relevant passage for this objective: {self.objective}"
        )[:600]
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                result = atlas_json([
                    "web:search", "--query", query, "--num-results", "1", "--no-log",
                ])
                hits = result.get("results") or result.get("hits") or []
                if not hits:
                    raise RuntimeError("search returned zero passages")
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < 2:
                    _warn(f"grounding preflight attempt {attempt + 1} failed: {exc}; retrying")
                    import time

                    time.sleep(2 * (attempt + 1))
        if last_exc is not None:
            raise RuntimeError(
                "web-grounding preflight failed; verify the web search route "
                f"or rerun with --no-require-grounding. Cause: {last_exc}"
            ) from last_exc

    def _record_consult(self, query: str, answer: str) -> None:
        control = self.callback.control if self.callback else None
        if not control:
            return
        try:
            envelope = {
                "local_temp_node_id": f"ground-{uuid.uuid4().hex[:10]}",
                "parent_ids": [control],
                "staged_payload": {
                    "title": f"grounding consult {self._consults}",
                    "summary": "Web search consult after the optimizer stalled.",
                    "content": f"## Query\n{query}\n\n## Grounded answer\n{answer}\n",
                    "kind": "insight",
                    "insights": ["web-grounded reflection context"],
                    "outcome": "completed",
                },
            }
            atlas_json(["node:create"], envelope)
        except Exception as exc:  # noqa: BLE001
            _warn(f"grounding consult record failed: {exc}")

    @staticmethod
    def _render_feedback(reflective_dataset: Any, limit: int) -> str:
        parts: list[str] = []
        if isinstance(reflective_dataset, dict):
            for _component, examples in reflective_dataset.items():
                for example in list(examples)[:limit]:
                    parts.append(json.dumps(example, indent=2, default=str)[:2000])
        return "\n\n".join(parts) if parts else "(no structured feedback this round)"

    @staticmethod
    def _extract_block(text: str) -> str:
        if "```" in text:
            chunks = text.split("```")
            if len(chunks) >= 3:
                body = chunks[1]
                # Drop a language tag on the opening fence.
                if "\n" in body:
                    first, rest = body.split("\n", 1)
                    if first.strip() and " " not in first.strip() and len(first.strip()) < 20:
                        return rest.strip()
                return body.strip()
        return text.strip()

    def __call__(
        self,
        candidate: dict[str, str],
        reflective_dataset: Any,
        components_to_update: list[str],
    ) -> dict[str, str]:
        import litellm  # gepa already depends on litellm

        with self._lock:
            self._proposals += 1
        feedback = self._render_feedback(reflective_dataset, self.feedback_examples)
        self._last_feedback_digest = feedback
        grounded = ""
        if self._stalled():
            context = self._consult_web()
            if context:
                grounded = (
                    "\n## Grounded context (from bounded web search — use it)\n"
                    f"{context}\n"
                )
                with self._lock:
                    self._since_improve = 0  # one consult per stall window

        updated: dict[str, str] = {}
        prompts: dict[str, str] = {}
        raw_outputs: dict[str, str] = {}
        for component in components_to_update:
            prompt = _GROUNDED_PROMPT.format(
                objective=self.objective,
                component=component,
                component_text=candidate.get(component, ""),
                feedback=feedback,
                grounded=grounded,
            )
            response = litellm.completion(
                model=self.reflection_lm,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.choices[0].message.content or ""
            updated[component] = self._extract_block(text)
            prompts[component] = prompt
            raw_outputs[component] = text

        # Reflection provenance for compat mode: key by the fingerprint of
        # what the engine will hand the evaluator (partial + merged shapes).
        if self.callback is not None:
            record = {
                "prompts": prompts,
                "raw_lm_outputs": raw_outputs,
                "grounded": bool(grounded),
            }
            merged = {**candidate, **updated}
            for key in {candidate_fingerprint(updated), candidate_fingerprint(merged)}:
                self.callback.pending_proposals[key] = record
        return updated
