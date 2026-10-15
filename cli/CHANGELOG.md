# Changelog

All notable changes to `@synsci/atlas` are documented here.

## [0.16.1] - 2026-10-15

- Correct company attribution and the confirmed support contact.
- Include the copyright and attribution notice in the npm package.

## [0.16.0] - 2026-10-15

- Move CLI source and npm release ownership into the private Atlas repository.
- Publish the graph CLI under Apache-2.0, independently of React UI dependencies.
- Preserve command names, profiles, authentication, and hosted wire contracts.
- Fix project listing so custom-titled roots are included and child notes are excluded.

### Removed — Atlas agent-skill distribution

- Removed every bundled Atlas `SKILL.md`, the agent installer and ambient hook,
  post-install promotion, and the public `atlas install` command.
- Moved the GEPA Python harness into the retained compatibility runtime so the
  retained optimize commands do not depend on, ship, or advertise a skill.

## [0.15.0] - 2026-08-23

### Changed — focused Gateway compatibility runtime

- Removed embedded agent execution, managed execution, and hosted synthesis
  commands from the compatibility CLI. Gateway now stays focused on durable
  research maps, evidence, runs, source retrieval, and agent-facing skills.
- Reduced the search contract to source indexing, deterministic library search,
  and metered `web:search` / `web:fetch`. Gateway returns source material while
  analysis and synthesis stay in the local coding agent.
- Updated the bundled skills and command documentation to match the smaller
  runtime, without changing the `@synsci/atlas` package, `atlas` executable, or
  existing API/config compatibility identifiers.

## [0.14.1] - 2026-08-20

### Changed — OpenScience Gateway product copy

- Renamed the installed banner, browser login, help, errors, agent adapters,
  command summaries, and all bundled skill guidance to Gateway.
- Preserved the `@synsci/atlas` package, `atlas` executable and commands,
  `atlas.json` / `.atlas` paths, `ATLAS_*` environment variables,
  `X-Atlas-*` wire headers, skill names, and code identifiers for compatibility.
- Added a package dry-run regression that rejects unapproved legacy product copy
  while explicitly checking the compatibility contract.

## [0.14.0] - 2026-08-06

### Restored — Nia-backed Atlas research runtime

- Restored the Atlas CLI source, search, grounded Q&A, Oracle, and async
  research commands backed by the server-side Nia integration.
- Restored project source scoping and Nia grounding for bundled Atlas skills.
- Kept Library out of the web app: this release restores only the backend and
  agent-facing Atlas surfaces.

## [0.13.2] - 2026-06-23

### Changed — `atlas-reproduce` is now "turn a paper into a graph"

- The `atlas-reproduce` skill leads with the end-to-end flow: hand the agent an
  **arXiv id**, it indexes the paper (`library:add --type research_paper`), finds
  the code, runs a **minimal reproduction**, and lays it out as a graph (paper →
  claim → setup → result) — **asking you for whatever the paper didn't say** and
  recording each answered gap as a `decision` node (honest, durable). The
  reproduced node is a launch point: `atlas autoresearch --project <node>`
  continues from it, filing the fan-out into the same graph. Then `atlas fork`
  carries the code-state so someone continues from yours.

### Fixed

- `atlas autoresearch` now prints the canonical node URL (`/nodes/<id>`) instead
  of a `/dashboard?node=` link that redirected away.

### Fixed — onboarding footguns

- **`atlas init` refuses to run in `$HOME` or a filesystem root** (pass `--force`
  to override). atlas.json activates ambient Atlas behavior for *every* session
  at or below it (the CLI walks up the tree to find it), so initializing your
  home directory silently scoped ambient mode to everything and bound it to a
  junk `Project: <username>`.
- **`atlas doctor` no longer reports `ok:false` for advisory warnings.** The
  verdict reflects only whether the lab is usable (backend, skills, auth). A
  stale spool entry or an expiring GitHub token warns without failing the check.
- **The Flight Recorder spool stops retrying a permanently-failing entry
  forever.** After 50 attempts an entry is quarantined to `~/.atlas/spool/failed/`
  (preserved, never lost) instead of re-failing every invocation and poisoning
  `doctor`.

## [0.13.1] - 2026-06-23

### Fixed — stop auto-retrying rate-limits

- `429` (rate limited) and `409` (conflict) are no longer auto-retried. They are
  deliberate, non-transient responses — retrying them in a loop only hammers the
  server and never succeeds (a 429 retry-storm can saturate the backend). The CLI
  now surfaces the friendly "rate limited, wait a moment" / "conflict, refetch"
  message and lets you back off. Only genuinely transient failures (`408`, `425`,
  `5xx`) are retried.

## [0.13.0] - 2026-06-23

### Added — `atlas autoresearch`, the one-command refereed campaign

The whole `atlas-autoresearch` protocol is now a single command. Point it at a
forked repo with a plain-English goal and it runs the entire campaign —
researchify → baseline → pre-register → search → referee → report — asking only
what it can't infer.

- **`atlas autoresearch --goal "<sentence>"`** auto-detects the artifact to
  optimize, generates a readable, editable benchmark in `.atlas/`
  (`benchmark.sh` + `score.py` + a files-unchanged Goodhart `gate.sh`), measures
  the seed baseline to validate the contract, **pre-registers a hypothesis +
  experiment plan before the first candidate** (the plan's timestamp is the
  guarantee), runs the GEPA `optimize:start` loop, then runs `optimize:verify`
  on **both the winner and the baseline** over N seeds and prints a verified
  before→after delta: `VERIFIED: 0.748 → 0.718 (Δ -0.030, p<0.05, n=10)`.
- `--metric` is inferred from the goal verb (lower/reduce/faster → `min`;
  raise/improve/beat → `max`); `--dry-run` previews the full plan without
  spending budget; `--scaffold-only` stops after generating the benchmark for
  review; `--target`/`--benchmark` override detection; `--budget 8h` runs to a
  wall-clock cap; `--resume` continues a campaign. Degrades gracefully: when a
  repo can't be auto-benchmarked it stops with a one-line fix, never a guess.
- It is an orchestration layer over the existing `optimize:start`/`verify`,
  `hypothesis:add`, and `experiment:plan` primitives — no new engine.

### Added — wall-clock budget + result contract for `optimize:start`

- **`optimize:start --max-seconds <N>`** sets a wall-clock budget (maps to
  gepa's `TimeoutStopCondition`, with a built-in fallback), composing with
  `--max-metric-calls`; "run it overnight" autonomy.
- The harness now writes a machine-readable `optimize-result.json` (control +
  winner node ids, stop reason) into the run dir, and `optimize:start` returns
  it — so wrappers learn the control node without scraping stdout.

### Removed — managed compute (`compute:*`)

- The `compute:options`, `compute:estimate`, `compute:lease`, `compute:list`,
  and `compute:release` commands have been removed. Provisioning compute is no
  longer part of the Atlas CLI.
- Provisioned compute is now a **Lambda Labs reseller** in the web dashboard's
  Compute tab: lease a GPU VM and get SSH access (Atlas generates a per-lease
  key). It runs on your own Lambda key when connected (free), otherwise it's
  funded from your CLI wallet (managed).
- Modal is an agent-runtime concern, not a user-facing lease. The agent sources
  its Modal key from your own key when connected, otherwise from the CLI wallet.

## [0.12.0] - 2026-06-22

### Added — managed compute (`compute:*`)

- **`compute:options`** lists provisionable SKUs with per-SKU funding (your
  own provider key = free, else managed = billed to your CLI wallet) and your
  current wallet balance.
- **`compute:estimate`** prices a prospective lease (`ceil(hours) x rate`) and
  reports whether your CLI wallet covers it.
- **`compute:lease`** provisions a sandbox. With a provider key set it runs on
  your own key for free; otherwise it's funded from your CLI wallet (a pre-auth
  hold is placed for the estimate and settled to the actual cost on release,
  refunding the remainder).
- **`compute:list` / `compute:release`** show and tear down leases; releasing a
  managed lease reconciles it to actual cost and refunds the unused remainder.
- Insufficient wallet credit surfaces a clear, backend-authored message: add
  your own key in Integrations, or top up your wallet in Billing.

## [0.11.0] - 2026-06-16

### Added — the results contract (EVAL.md) + zero-config run command

- **`run:record` auto-attaches an EVAL.md-style results doc.** A run's
  `EVAL.md` (or `.atlas/EVAL.md`) is folded into the node body and rendered
  results-first, so every run carries one obvious, comparable results surface
  — the same role EVAL.md plays for an experiment. Override with
  `--eval <path>`; opt out with `--no-eval`. `notebook:cell` never folds one in.
- **`atlas init` auto-detects a run command** from common run scripts
  (`run.sh`, `scripts/run.sh`, `speedrun.sh`, `.atlas/run.sh`, …) and records
  it as `run_command` in `atlas.json`. Override with `--run-command`.

## [0.10.0] - 2026-06-16

### Added — ambient research mode

- **`atlas init`** writes `atlas.json`, the opt-in activation contract for a
  research repo: project id, scoped source ids, and ambient preferences
  (`auto.enabled`, `auto.log`, `auto.web`, `auto.capture`).
- **`log:append` / `log:tail` / `log:search`** — lightweight, spool-safe
  research-log breadcrumbs. `project_id` auto-fills from `atlas.json`.
- **`web:search` / `web:fetch`** — Atlas-metered web search/fetch that can
  log provenance to the project research log when run inside a project.
- **`brief`, `log:*`, `web:*` auto-resolve their project** from `atlas.json`,
  honoring `auto.enabled` (with a `--no-project` escape and a stderr note).
- **`atlas install` now wires a deterministic post-tool hook** into Claude
  Code (`~/.claude/settings.json`) and Cursor (`~/.cursor/hooks.json`) that
  logs web activity to the project log. Strict no-op outside `atlas.json`
  projects; `--no-hooks` skips it and `atlas install --uninstall` removes it.

### Added — graph collaboration + code-state + papers

- **`atlas fork --node <id>`** — fork any visible node/subtree (incl. public
  graphs) into your account as a new private graph, preserving code-state and
  recording `forked_from` provenance.
- **Code-state is trustworthy**: pins persist into `semantic_data.code_state`,
  `reproduce` prefers the immutable tag and verifies remote reachability, and
  `branch` / `map:export` / `map:import` carry code-state.
- **`atlas-paper` skill** — turn a completed graph (claims, runs, evidence,
  sources, code-state) into a publication-style paper draft. 9 bundled skills.

### Changed

- Visibility and collaborators are now graph-scoped: they live on the project
  root and every node inherits them (no per-node public/private).

## [0.9.2] - 2026-06-12

### Added — campaign-grade optimize loop

Everything a long, serious optimization campaign needs, live-verified
end-to-end (mid-run stop, parallel overlap, resume seed, referee verdict):

- **`optimize:start --parallel K`** — K candidates evaluated concurrently
  (gepa parallel proposal pipelines; values > 1 pin a known-good gepa build).
  Evaluator, callback, registry, and grounded proposer are now thread-safe;
  worktree creation retries through git lock contention.
- **`optimize:verify`** — the referee. Re-runs a recorded candidate's
  benchmark N times at its exact commit (`ATLAS_EVAL_SEED=0..N-1` exported
  per replication), records the replications as a run cluster, computes
  mean/std and a one-sided t-test against `--threshold` (scipy-free,
  validated against published reference verifiers to 6 decimals), and
  attaches a referee-report node. Accepts a candidate node or a control
  node (verifies its best). A single search-time score is a point
  estimate; claims go through `optimize:verify`.
- **Resume continues the search, not just the node.** `--resume <control>`
  now seeds from the best recorded candidate's exact content
  (`best_node_id` → commit → `git show`), falling back to the on-disk
  target when no best exists.
- **Mid-run stop actually works.** GEPA's `FileStopper` is wired into the
  stop conditions, so `optimize:stop` interrupts at the next iteration
  boundary (previously the stop file was only read post-run). Stale stop
  files are cleared at startup.

- **`atlas-autoresearch` skill** — the campaign protocol on top of
  `atlas-optimize`: researchify any repo + measurable goal into a
  benchmark, pre-register tiers/budget/stop-rule before the first
  candidate, search (parallel, grounded), referee with `optimize:verify`,
  report from the map. Zero task-specific content; the pristine-harness
  transplant pattern and ablation-arm protocol are part of the skill.

### Changed — skill consolidation (11 → 8)

One job per skill, intent-matched descriptions, no more `atlas-auto` vs
`atlas-autoresearch` ambiguity:

- `atlas-record` + `atlas-loop` → **`atlas-lab`** (the lab notebook: run
  capture + the research loop, one document).
- `atlas-plan` + `atlas-auto` → **`atlas-frontier`** (plan-only and
  autonomous modes of the same frontier machinery).
- `atlas-tree` folded into the base `atlas` skill (read-only map commands).
- The base skill's router table is now intent-phrased ("log this run" →
  `atlas-lab`, "what's next" → `atlas-frontier`, "make it better against
  a metric" → `atlas-optimize`, "prove it" → `atlas-autoresearch`).
- `atlas install` sweeps dangling symlinks left by retired skill names.

### Fixed

- `optimize:start` now installs `litellm` + `cloudpickle` alongside gepa
  (litellm became an optional extra of gepa; the reflection path needs it).
- The harness exits non-zero on `runtime_error` instead of reporting success.
- Serial runs pin `gepa>=0.1.1` so stale uv caches can't resolve ancient builds.

## [0.9.1] - 2026-06-11

### Fixed — optimize loop verified end-to-end

Ran the full loop live (local backend + real gepa engine + real CLI) and
fixed what broke:

- **Compat mode for released gepa.** PyPI gepa predates engine callbacks
  (`GEPAConfig.callbacks` only exists on git main). The harness now
  detects support: with a callback-aware gepa it records from engine
  events (exact lineage); otherwise the evaluator drives recording with
  best-so-far lineage, budget ticks, and reflection provenance matched
  by candidate fingerprint. Same map either way.
- `optimize:progress` calls from the bridge now use discrete flags
  (`--payload-json` is not part of that command's schema).
- Backend: node read models (`node:show`, `node:list`, graph tree) now
  include `semantic_data` — scorecard rings, optimize panels, and
  criterion badges render from real data, not just previews.
- Backend: `optimize:progress` no longer lets the entropy scrubber
  mangle `run_dir` (it's a path, not a secret); `optimize:stop` depends
  on it byte-exact.

## [0.9.0] - 2026-06-11

### Added — the optimize loop (GEPA × Atlas)

- `optimize:start` — run a GEPA optimization over a prompt/config/code
  artifact against a shell benchmark, one command. Isolated git worktree
  per candidate, `--gate` Goodhart guards, every candidate recorded into
  the map with lineage + per-example scorecard + the exact commit
  (`refs/atlas/optimize/…`), live budget on the control node, score chart
  on completion. `--ground` enables library-grounded reflection: when the
  search stalls, the project's indexed sources are consulted and the
  answer folded into GEPA's reflection prompt (each consult recorded).
- `optimize:status` / `optimize:stop` / `optimize:progress` — read, stop
  (graceful, via GEPA's FileStopper), and stream control-node run state.
- `run:chart` — vega-lite score progression (points by outcome +
  best-so-far line) from any project's runs, attached as evidence the web
  app renders. General-purpose, not GEPA-specific.
- `run:record` gains `--parent-run` (candidate lineage as real edges),
  `--candidate-idx`, and `--scorecard-json` (evaluation_v1 per-example
  results, rendered as pass/fail rings in the graph).
- `AtlasCallback` (bundled in the atlas-optimize skill): add one callback
  to ANY existing gepa run — `optimize_anything` or classic
  `gepa.optimize`/DSPy — and the run streams into Atlas: candidates,
  lineage, scorecards, budget, and the reflection prompt + raw LM output
  behind every accepted candidate attached as evidence.

### Changed

- atlas-optimize skill rewritten around the three entry points
  (zero-code `optimize:start`, one-line `AtlasCallback`, grounded
  reflection) with the benchmark contract upgraded: feedback-rich metrics,
  mandatory Goodhart gate pairing for constructed benchmarks, held-out
  splits.

## [0.8.2] - 2026-06-11

### Added

- Post-install banner: ATLAS wordmark + 3-command quickstart on `npm i -g`
  (TTY-aware, silent in CI, can never fail an install).
- `library:search --mode` documents the real modes (universal | targeted |
  web | deep); `library:update` gains a proper schema.

### Changed

- Research command summaries no longer name the upstream knowledge vendor.

## [0.8.1] - 2026-06-11

### Added — code-state auto-capture ("GitHub for science")

- **`run:record` auto-captures git state.** When recording from inside a
  git repo, the CLI detects `repo_url` / `branch` / `commit sha` from the
  working tree and stores them on the run node — every result is linked to
  the exact code that produced it, no separate `repo:capture` call needed.
  Opt out with `--no-git`.
- **Dirty trees are flagged.** Uncommitted changes at record time are
  stored as `git_dirty`; `atlas reproduce --check` fails on dirty runs
  (the sha alone would overstate reproducibility).
- Skills updated: commit-before-record guidance, pinning milestones
  (`repo:capture --pin true`), and the fork story (`map:export` →
  `map:import`) in the base skill.

### Changed

- Versions older than the current release are now marked deprecated on npm
  with an upgrade notice.

## [0.8.0] - 2026-06-10

### Added — the research loop

- **`atlas brief`** — the project context packet for agents: open
  hypotheses, recent runs, failure clusters, decisions, open branches, and
  `suggested_next` (runnable next actions). Start every session with it.
- **Research verbs**: `hypothesis:add` / `hypothesis:update` (lifecycle:
  proposed → testing → supported / weakened / rejected, with `--because`
  citations), `experiment:plan` (declares the hypothesis, config, metric,
  and success criterion *before* the run; pre-allocates the cluster key),
  `decision:add` (links the runs/evidence a decision rests on),
  `eval:define`.
- **`run:record --plan <plan>`** binds a run to its experiment plan: the
  run inherits the plan's `run_cluster_key` and the backend evaluates
  `criterion_met` against the plan's success criterion.
- **`atlas leaderboard`** — rank runs by a metric dot-path with the winner
  marked (`run:compare` also gains `--sort/--direction/--best`).
- **`atlas reproduce --node <id>`** — reproducibility packet: exact config,
  captured code state (repo/commit/pin), dataset ref, success criterion,
  and what's missing (`--check` fails when incomplete).
- **`project:create`** — dedupe-aware find-or-create for the cwd/repo
  project root; safe to re-run every session.
- **Library → graph fusion**: `library:ask --attach <node>` and
  `library:search --save-to <node>` persist grounded answers / hits as
  evidence artifacts on a node in one command.
- **New `atlas-loop` skill** — the full scientific loop with a worked
  example; the base `atlas` skill is now a router table.

### Changed — naming conventions (see cli/CONVENTIONS.md)

- Singular namespaces are canonical: `node:*`, `label:*`, `key:*`,
  `secret:*`, `integration:*`, `project:merge`.
- "run" now always means an experiment run: Flight Recorder is `run:*`,
  managed node executions are `exec:start/list/stop`, async jobs are
  `library:jobs:*` / `research:jobs:*`. `github:refresh` is
  `github:reconnect`.
- **Every pre-0.8 name keeps working** as a hidden alias — published
  scripts and skills do not break.
- Canonical target flags everywhere: `--project`, `--node`, `--plan`,
  `--hypothesis` (slug-resolved); longer spellings remain accepted.

### Fixed

- `run:compare` now walks descendants (depth-capped) instead of only
  direct children, so plan-nested runs appear in the matrix.
- Spool entries record `attempts` / `last_error` / `last_attempt_at`;
  `doctor` reports pending count, oldest-entry age, and the last flush
  error — a stuck spool can no longer hide (post-0.7.3 hardening).

## [0.7.3] - 2026-06-06

### Fixed

- **Flight Recorder writes were silently 404'ing in production.**
  `runs:record`, `note:add`, and `notebook:cell` were calling
  `/api/v1/api/v1/runs:record` and `/api/v1/api/v1/nodes/commit-new`
  (double-prefixed against the already-`/api/v1`-suffixed `baseUrl`). Every
  capture spooled successfully on the client but the server never saw it.
  Routes are now relative to `baseUrl` and both shims are live again.
- `note:add` was also sending the legacy `{create, update, commit}` envelope.
  Now sends the `{local_temp_node_id, parent_ids, staged_payload}` shape the
  `/nodes/commit-new` route actually expects.
- `flushSpool` strips a leading `/api/v1` from any legacy spool entry written
  by an earlier broken install so a backlog from before 0.7.3 actually drains
  instead of permanently retrying into 404.

### Companion backend change

- `POST /api/agent/projects` and `GET /api/agent/projects` now accept a
  `dedupe_key`. When provided to POST, the route returns the user's existing
  project root (`{"deduped": true}`) instead of creating a near-duplicate
  with the same logical identity (folder path, repo URL, etc.). When provided
  to GET, the route returns just the matching project for a cheap "find or
  create" round-trip. Stored client-side on the existing
  `external_transcript_ref` field under a namespaced `atlas-project-dedupe:`
  prefix — no schema migration required.

## [0.7.2] - 2026-06-06

### Changed

- README rewritten around the v0.7.1 ergonomics: pretty/table output, slug
  resolution, `--node` / `--project` aliases, `project:list`, `library:retry`,
  `keys:list --active-only`. Drops `--format=json` from every example since
  TTY now renders pretty by default and pipes still emit JSON. Adds an
  output-formats table, environment variables, and the new "discovery"
  error messages.

## [0.7.1] - 2026-06-06

### Added

- **Pretty + table rendering that actually works.** Per-command views for
  `nodes:list`, `nodes:show`, `library:list`, `library:search`,
  `library:ask`, `keys:list`, `usage:summary`, `integrations:status`,
  `whoami`, `doctor`, `runs:list`, `evidence:list`, `project:list`. Status
  glyphs, relative timestamps (`3d ago`), footer hints, smart truncation.
  Generic fallback picks priority columns and drops large object-shaped
  fields, so unknown commands also render readably.
- **TTY-aware default format.** When stdout is a terminal the default is
  `pretty`; piped output (`| jq`, scripts, CI) stays `json` so existing
  automation is unaffected. Explicit `--format=json` is always honoured.
- **Slug resolution.** `--node-id`, `--project-id`, and `--root-node-id`
  now accept slugs (`able-helm-1359`). The CLI resolves them via
  `/nodes/resolve-by-slug` before dispatch. New `--node` / `--project`
  short aliases.
- **`atlas project:list`** — find a project root to use as `--project-id`
  without hand-paging `/nodes` JSON.
- **`atlas library:retry --source-id <id>`** — re-trigger indexing for a
  source stuck in `error` state.
- **`atlas keys:list --active-only`** — hide revoked keys client-side.
- **Doctor checks integration freshness.** `atlas doctor` now hits
  `/auth/integrations/status` and emits a warning when a connected
  GitHub token is expired or expiring within 7 days. Stops returning
  `ok:true` while a connected integration is broken.

### Changed

- **Required-field errors point at a discovery command.** Instead of just
  `node_id is required`, the CLI now says
  `--node-id is required — try \`atlas nodes:list\` or pass a slug like
  \`able-helm-1359\``. Equivalent hints for `--project-id`, `--source-id`,
  `--artifact-id`, `--key-id`, `--execution-id`, etc.
- **`friendlyHttpError` translates raw backend leakage.** asyncpg
  `invalid UUID` errors, 401/403/404/409/422/429, and 5xx now surface as
  actionable text instead of raw response bodies.
- **`agent:run` boots locally.** The hardcoded `/workspace/outputs` is
  gated on Modal-sandbox env vars; outside the sandbox it falls back to
  `os.tmpdir()/atlas-agent-outputs/` so the runtime doesn't crash with
  `mkdir '/workspace'`.
- **Help groups cleaned up.** The "other" catch-all is gone — `install`
  → `setup`, `repo:*` → `integrations`, `note:add` / `notebook:cell`
  → `journal`.
- **Pagination flags documented.** `nodes:list` and `library:list` now
  expose `per_page`, `page`, `cursor`, `limit`, `kind`, `type`, `status`
  in `atlas help` instead of returning "Optional flags: None".

## [0.7.0] - 2026-06-04

### Added

- **`atlas install`** — one command that detects every coding agent on
  this machine and drops the bundled Atlas skills into wherever each
  one looks. Seven supported today: Claude Code, Cursor, OpenAI Codex
  CLI, Windsurf, Aider, Continue (VS Code), Goose.
  - **Symlink mode** for Claude Code: each bundled skill becomes a
    symlink under `~/.claude/skills/` pointing back at the
    npm-global install. `npm i -g @synsci/atlas@latest` updates the
    agent for free.
  - **Whole-file adapter** for Cursor (MDC with `alwaysApply: true`),
    Aider, Continue, Goose: a single concatenated `atlas.md` /
    `atlas.mdc` adapter at the agent's expected path.
  - **Managed block** for Codex `AGENTS.md` and Windsurf
    `global_rules.md`: inserts or refreshes a
    `<!-- BEGIN atlas-skills -->` … `<!-- END atlas-skills -->` block
    inside the user's existing file. Pre-existing content outside the
    markers is preserved exactly.
  - Flags: `--agent=<csv>` (non-interactive), `--dry-run` (print the
    plan), `--uninstall` (reverses any of the above cleanly), `--yes`
    (auto-select every detected agent in non-interactive shells).
  - Re-running install is idempotent. Detection is conservative; pass
    `--agent=<id>` to force-install ahead of the agent's first launch.

## [0.6.2] - 2026-06-04

### Changed

- `atlas help` now defaults to a **readable text** listing of commands
  grouped by domain. The full JSON dump (schema + descriptions for every
  command) used to be the default and was unusable in a terminal; it's
  still available via `--format=json` for agents and scripts.
- The browser callback page after `atlas login` is now a proper styled
  page (Atlas "Soft Porcelain" palette, Computer Modern serif, respects
  `prefers-color-scheme`) instead of an unstyled `<p>` tag. Pure
  cosmetic — the CLI still resolves the login before the page renders.

## [0.6.1] - 2026-06-04

### Changed

- `atlas login` now prints the approval URL to stderr **before** trying
  to open the browser, so headless / SSH / container shells where the
  browser can't auto-open still have a URL to paste somewhere signed
  in. Previously the URL was hidden and a silent ``open()`` failure
  left the user staring at nothing.
- `atlas login` success now prints a human one-liner to stderr
  (``✓ Logged in as <email>``) while still returning the same JSON
  payload on stdout, so scripts using ``--format=json`` are unchanged.

## [0.6.0] - 2026-06-03

### Added

- **Flight Recorder**: capture experiment runs, failures, notebook cells,
  and freeform notes into Atlas as durable nodes.
  - `atlas runs:record` — post a single run (config, metrics, stdout_tail,
    outcome, failure_mode, run_cluster_key) as an empirical node under
    the project. Secrets are scrubbed server-side before storage.
  - `~/.atlas/spool/` — when the backend is unreachable, runs are
    queued locally and flushed on the next CLI invocation. No daemon,
    no watcher; just files the next call picks up. Zero data loss
    when offline.
  - `atlas runs:compare` — render a comparison matrix across runs in
    a project / cluster. Dot-path columns (`config.lr`,
    `metrics.val_loss`) plus node columns (`title`, `outcome`,
    `failure_mode`, `run_cluster_key`). `--format=table` returns a
    markdown rendering for terminal echo.
  - `atlas note:add` — drop a freeform note as an insight node under
    a project. First line of `--text` becomes the title.
  - `atlas notebook:cell` — capture a single notebook cell + output
    as an empirical node; thin wrapper over `runs:record` with cell
    metadata folded into `config`.
- New bundled skill `atlas-record` documenting when/what to capture,
  cluster-key conventions, and anti-patterns.

## [0.5.12] - 2026-06-01

### Changed

- Renamed bundled skills from `atlas-lookahead` to `atlas-plan` and from
  `atlas-to-graph` to `atlas-map` to match Atlas map vocabulary.
- Added `atlas-optimize` to package docs and onboarding prompts.
- Replaced undefined Context wording with library-backed guidance.

### Removed

- Removed the bundled `atlas-prove` skill from the shipped skill bundle.

## [0.5.11] - 2026-05-19

### Changed

- Updated bundled skills for the final `nodes:*` command vocabulary.
- Expanded `atlas-search` guidance around indexing, source inspection,
  Nia-backed search, grounded Q&A, Oracle-style answers, async library jobs,
  and async deep research.
- Refined app guide copy and examples to match the updated skill workflows.

## [0.5.10] - 2026-05-19

### Changed

- Renamed graph object commands from `entry:*` to `nodes:*`.
- Renamed draft coordination commands from `draft:claim`, `draft:touch`,
  and `draft:release` to `draft:lock`, `draft:renew`, and `draft:unlock`.
- Moved node-attached file listing from `evidence:entry-files` to
  `nodes:files`.
- Updated bundled skills, docs, and app guide copy around the `nodes`, `links`,
  `evidence`, and `library` vocabulary.

## [0.5.9] - 2026-05-19

### Changed

- Renamed the public Atlas CLI command surface to product-native vocabulary:
  `nodes`, `map`, `draft`, `evidence`, `library`, `runs`, `labels`,
  `access`, `keys`, `config`, `secrets`, and `ops`.
- Removed endpoint-shaped legacy command names from runtime help, bundled
  skills, and product docs. REST routes and backend compatibility endpoints did
  not change.
- Added a migration note for SynSci scripts and prompts that invoked old Atlas
  command names.

## [0.5.6] - 2026-05-16

### Changed

- Replaced command-list agent install guidance with a single copyable onboarding
  prompt.
- Clarified that Atlas skills are bundled inside the CLI package and do not
  require a separate install step.

## [0.5.5] - 2026-05-16

### Changed

- Restored the web `/cli` page to the SynSci agent CLI dashboard.
- Moved Atlas setup and agent onboarding guidance to the `/atlas` page.
- Added bundled `atlas-prove` and `atlas-search` skills.
- Removed upstream implementation names from public Atlas package and docs copy.

## [0.5.4] - 2026-05-16

### Changed

- Added explicit browser-first and headless-agent onboarding instructions.
- Clarified that autonomous agents use `ATLAS_API_KEY` and discover command
  schemas with `atlas help --format=json`.
- Updated bundled skill docs to include Atlas library, research, and usage
  commands.

## [0.5.3] - 2026-05-16

### Changed

- Rebuilt the CLI as a direct HTTP Atlas runtime.
- Ships only the Atlas binary, direct runtime files, README, LICENSE, and six
  bundled skills.
- Exposes map, evidence, export/import, integration, key, library, research,
  and usage commands through Atlas REST endpoints.
- Exposes Atlas-native `library:*`, `research:*`, and `usage:summary`
  commands.

### Removed

- Removed legacy host setup writers, shell script runtime, parity harness files,
  and non-core skill variants from the published package.
