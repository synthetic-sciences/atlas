import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const BASE_SCHEMAS = JSON.parse(
  readFileSync(join(__dirname, "atlas-command-schemas.json"), "utf8"),
);

const objectSchema = (properties = {}, required = []) => ({
  type: "object",
  properties,
  required,
  additionalProperties: false,
});

const stringParam = (description) => ({ type: "string", description });
const intParam = (description) => ({ type: "integer", description });
const boolParam = (description) => ({ type: "boolean", description });

const SCHEMA_OVERRIDES = {
  "secret:set": objectSchema({
    name: stringParam("Gateway CLI profile name. Defaults to the active profile."),
  }),
  "secret:clear": objectSchema({
    name: stringParam("Gateway CLI profile name. Defaults to the active profile."),
  }),
  "program:snapshot": objectSchema(
    { node_id: stringParam("Node ID.") },
    ["node_id"],
  ),
  "map:view": objectSchema({
    node_id: stringParam("Scope to a root node."),
    depth: intParam("Max depth."),
    max_nodes: intParam("Max nodes in response."),
    page_size: intParam("Map page size."),
    cursor: stringParam("Cursor returned by the previous map page."),
    filter: stringParam("Comma-separated node filter tokens."),
    exclude: stringParam("Comma-separated exclude shorthand tokens."),
  }),
  "evidence:link": objectSchema(
    {
      node_id: stringParam("Node ID."),
      remote_artifact_id: stringParam("Stable linked-evidence ID."),
      title: stringParam("Artifact title."),
      url: stringParam("Public HTTPS JSON URL."),
      rows_path: stringParam("Dotted path resolving to the row list."),
      row_id: stringParam("Dotted path resolving to each row ID."),
      cache_ttl_seconds: intParam("Freshness TTL in seconds."),
      force_refresh: boolParam("Bypass the cached evidence when true."),
    },
    ["node_id", "remote_artifact_id", "title", "url", "rows_path", "row_id"],
  ),
  "evidence:refresh": objectSchema(
    {
      node_id: stringParam("Node ID."),
      remote_artifact_id: stringParam("Stable linked-evidence ID."),
      title: stringParam("Artifact title."),
      url: stringParam("Public HTTPS JSON URL."),
      rows_path: stringParam("Dotted path resolving to the row list."),
      row_id: stringParam("Dotted path resolving to each row ID."),
      cache_ttl_seconds: intParam("Freshness TTL in seconds."),
    },
    ["node_id", "remote_artifact_id", "title", "url", "rows_path", "row_id"],
  ),
  "evidence:delete-bulk": objectSchema(
    {
      node_id: stringParam("Owning node."),
      artifact_ids: stringParam("Comma-separated evidence IDs."),
      expected_revision: intParam("Optimistic lock."),
    },
    ["node_id", "artifact_ids", "expected_revision"],
  ),
  "github:link": objectSchema(),
  "github:set": objectSchema({
    token: stringParam("GitHub personal access token (fine-grained or classic) with Contents read/write."),
    token_env: stringParam("Environment variable holding the GitHub PAT (keeps it out of shell history)."),
  }),
  "integration:wandb:set": objectSchema({
    api_key: stringParam("W&B API key."),
    api_key_env: stringParam("Environment variable containing the W&B API key."),
  }),
  "integration:huggingface:set": objectSchema({
    token: stringParam("Hugging Face access token."),
    token_env: stringParam("Environment variable containing the Hugging Face access token."),
  }),
  "key:list": objectSchema({
    limit: intParam("Maximum keys to return."),
    offset: intParam("Number of newest keys to skip."),
    active_only: boolParam("Hide revoked keys. Filters client-side after the fetch."),
  }),
  "project:list": objectSchema({
    limit: intParam("Maximum nodes to scan when finding projects."),
    orphaned: boolParam("Filter to projects with zero children — usually leftovers from broken / aborted sessions, safe to delete."),
  }),
  "project:create": objectSchema({
    title: stringParam('Project title. Defaults to "Project: <folder>".'),
    path: stringParam("Folder identity for the dedupe key (defaults to the current directory)."),
    repo_url: stringParam("Repo identity for the dedupe key (defaults to `git remote get-url origin` when available)."),
  }),
  init: objectSchema({
    title: stringParam('Project title. Defaults to "Project: <folder>".'),
    path: stringParam("Folder where atlas.json should be written (defaults to the current directory)."),
    repo_url: stringParam("Repo identity for the dedupe key (defaults to `git remote get-url origin` when available)."),
    no_ambient: boolParam("Initialize atlas.json with ambient behavior disabled."),
    no_log: boolParam("Disable ambient research-log capture in atlas.json."),
    no_web: boolParam("Prefer native web tools instead of Gateway web search/fetch."),
    web_mode: stringParam("Ambient web mode: prefer_atlas | native | log_only."),
    capture_mode: stringParam("Ambient capture mode: suggest | auto | off."),
    privacy: stringParam("Project privacy hint stored in atlas.json (default private)."),
    run_command: stringParam("Run command for this project's experiments; auto-detected from common run scripts (run.sh, speedrun.sh, …) when omitted."),
  }),
  "project:merge": objectSchema(
    {
      canonical: stringParam("Canonical project node id or slug — the survivor."),
      absorb: stringParam("Comma-separated project ids/slugs to absorb into the canonical."),
    },
    ["canonical", "absorb"],
  ),
  fork: objectSchema(
    {
      node_id: stringParam("Node UUID or slug to fork into your account."),
      include_descendants: boolParam("Include descendants of the selected node (default true)."),
      max_nodes: intParam("Maximum nodes to fork."),
      title: stringParam("Optional title for the imported root node."),
    },
    ["node_id"],
  ),
  "node:share": objectSchema(
    {
      node_id: stringParam("Node UUID or slug (resolved automatically)."),
      visibility: stringParam("private | unlisted | public."),
    },
    ["node_id", "visibility"],
  ),
  "node:list": objectSchema({
    per_page: intParam("Page size (default 50, max 200). Use --cursor to walk pages."),
    page: intParam("Page index for offset-paginated callers (1-based)."),
    cursor: stringParam("Opaque cursor from a previous response; preferred over --page."),
    limit: intParam("Alias for --per-page accepted for ergonomic parity with other list commands."),
    kind: stringParam("Filter by node kind (project|insight|empirical|untyped)."),
    visibility: stringParam("Scope (my_nodes|shared_with_me|public)."),
  }),
  "key:create": objectSchema({
    name: stringParam("Human-readable key name."),
    expiry_days: intParam("Days until expiry."),
  }),
  "log:append": objectSchema(
    {
      project_id: stringParam("Project node id. Auto-filled from atlas.json when available."),
      entry_type: stringParam("Entry type, e.g. note|search|web_fetch|decision|failure|result."),
      title: stringParam("Short human-readable entry title."),
      body: stringParam("Entry body, or @file.md."),
      refs_json: stringParam("JSON array of references, or @refs.json."),
      payload_json: stringParam("Whole log entry body as JSON, or @entry.json."),
    },
    ["title"],
  ),
  "log:tail": objectSchema(
    {
      project_id: stringParam("Project node id. Auto-filled from atlas.json when available."),
      entry_types: stringParam("Comma-separated entry types to include."),
      since: stringParam("ISO timestamp lower bound."),
      limit: intParam("Maximum entries."),
    },
  ),
  "log:search": objectSchema(
    {
      project_id: stringParam("Project node id. Auto-filled from atlas.json when available."),
      query: stringParam("Text to search in log titles and bodies."),
      limit: intParam("Maximum entries."),
    },
    ["query"],
  ),
  "web:search": objectSchema(
    {
      query: stringParam("General web search query."),
      project_id: stringParam("Optional project id for quota attribution and provenance logging."),
      num_results: intParam("Number of results, 1-25."),
      top_k: intParam("Alias for num_results."),
      category: stringParam("Optional Exa category hint; omit for unbiased web search."),
      search_type: stringParam("auto | neural | keyword."),
      log: boolParam("Append a web_search entry to the project research log when project_id is set."),
    },
    ["query"],
  ),
  "web:fetch": objectSchema(
    {
      url: stringParam("URL to fetch and extract."),
      project_id: stringParam("Optional project id for quota attribution and provenance logging."),
      with_summary: boolParam("Include provider summary when available."),
      text_limit: intParam("Maximum extracted text characters to return."),
      log: boolParam("Append a web_fetch entry to the project research log when project_id is set."),
    },
    ["url"],
  ),
  "account:update": objectSchema({
    display_name: stringParam("Display name."),
    full_name: stringParam("Full name."),
    avatar_url: stringParam("Avatar URL."),
    github_username: stringParam("GitHub username."),
    timezone: stringParam("IANA timezone."),
  }),
  "config:list": objectSchema(),
  "config:show": objectSchema({
    name: stringParam("Gateway CLI profile name. Defaults to the active profile."),
  }),
  "config:set": objectSchema({
    name: stringParam("Gateway CLI profile name. Defaults to the active profile."),
    base_url: stringParam("Gateway API base URL."),
    api_key_env: stringParam("Environment variable containing the Gateway API key."),
    default_format: stringParam("Default output format."),
    timeout_ms: intParam("Default request timeout in milliseconds."),
    retry_max: intParam("Default transient retry count."),
    active: boolParam("Make this profile active. Defaults to true."),
  }),
  "config:unset": objectSchema({
    name: stringParam("Gateway CLI profile name. Defaults to the active profile."),
  }),
  "node:history": objectSchema(
    {
      node_id: stringParam("Node ID."),
      limit: intParam("Maximum audit events to return."),
    },
    ["node_id"],
  ),
  "node:resolve": objectSchema(
    {
      slug_name: stringParam("Slug text."),
      context_node_id: stringParam("Disambiguating context node."),
      detail: stringParam("compact or full response detail."),
    },
    ["slug_name"],
  ),
  "node:save": objectSchema(
    {
      node_id: stringParam("Node ID."),
      payload_json: stringParam("Save envelope JSON."),
      repo_url: stringParam("Captured repo URL (e.g. $(git remote get-url origin))."),
      branch_name: stringParam("Captured branch (e.g. $(git rev-parse --abbrev-ref HEAD))."),
      head_commit_sha: stringParam("Captured commit SHA (e.g. $(git rev-parse HEAD))."),
    },
    ["node_id", "payload_json"],
  ),
  "node:create": objectSchema(
    {
      payload_json: stringParam("Create-and-save envelope JSON."),
      repo_url: stringParam("Captured repo URL (e.g. $(git remote get-url origin))."),
      branch_name: stringParam("Captured branch (e.g. $(git rev-parse --abbrev-ref HEAD))."),
      head_commit_sha: stringParam("Captured commit SHA (e.g. $(git rev-parse HEAD))."),
    },
    ["payload_json"],
  ),
  "repo:capture": objectSchema(
    {
      node_id: stringParam("Node ID to attach the captured code state to."),
      repo_url: stringParam("Repo URL, e.g. $(git remote get-url origin)."),
      branch_name: stringParam("Branch, e.g. $(git rev-parse --abbrev-ref HEAD)."),
      head_commit_sha: stringParam("Commit SHA, e.g. $(git rev-parse HEAD)."),
      pin: boolParam("Also pin the captured commit as an immutable tag."),
      tag: stringParam("Override the pin tag (defaults to atlas/<slug>-r<rev>)."),
    },
    ["node_id"],
  ),
  "draft:derive-hypothesis": objectSchema(
    {
      node_id: stringParam("Staged node ID."),
      expected_revision: intParam("Optimistic lock."),
      force: boolParam("Overwrite an existing hypothesis."),
    },
    ["node_id", "expected_revision"],
  ),
  "draft:derive-insights": objectSchema(
    {
      node_id: stringParam("Staged node ID."),
      expected_revision: intParam("Optimistic lock."),
      force: boolParam("Overwrite existing insights."),
    },
    ["node_id", "expected_revision"],
  ),
  "ops:maps:list": objectSchema({
    tag_id: stringParam("Filter by map label ID."),
    kind: stringParam("Filter by root node kind."),
    owner_user_id: stringParam("Filter by owner user ID."),
    created_after: stringParam("Filter roots created at or after this ISO timestamp."),
    created_before: stringParam("Filter roots created before this ISO timestamp."),
    cursor: stringParam("Pagination cursor."),
    page_size: intParam("Maximum maps to return."),
  }),
  "ops:maps:export": objectSchema(
    {
      root_node_id: stringParam("Root node ID to export."),
      max_nodes: intParam("Maximum nodes in the export."),
    },
    ["root_node_id"],
  ),
  "ops:maps:export-stream": objectSchema({
    tag_id: stringParam("Filter by map label ID."),
    kind: stringParam("Filter by root node kind."),
    owner_user_id: stringParam("Filter by owner user ID."),
    created_after: stringParam("Filter roots created at or after this ISO timestamp."),
    created_before: stringParam("Filter roots created before this ISO timestamp."),
    cursor: stringParam("Pagination cursor."),
    page_size: intParam("Maximum maps to export."),
    max_nodes: intParam("Maximum nodes in each map export."),
  }),
  "evidence:download": objectSchema(
    {
      storage_path: stringParam("Evidence storage path."),
    },
    ["storage_path"],
  ),
  "map:export": objectSchema(
    {
      node_ids: stringParam("Comma-separated list of node identifiers to include."),
      include_descendants: boolParam("Include descendants of the selected nodes."),
      max_nodes: intParam("Maximum nodes in the export."),
    },
    ["node_ids"],
  ),
  "run:compare": objectSchema(
    {
      root: stringParam("Project node id (parent of the runs to compare). --project is accepted as an alias."),
      cluster: stringParam("Optional run_cluster_key filter (e.g. resnet50/cifar10/lr-sweep)."),
      columns: stringParam("Comma-separated columns; node fields (title, outcome, failure_mode, run_cluster_key, criterion_met, created_at) or dot-paths into run data (config.lr, metrics.val_loss)."),
      outcome: stringParam("Filter rows to one stored outcome (completed | failed | inconclusive | canceled)."),
      sort: stringParam("Column or dot-path to order rows by (numeric-aware)."),
      direction: stringParam("asc (default) or desc."),
      best: boolParam("Include a `best` field with the top row after sorting."),
      format: stringParam("json (default) or table (adds a markdown rendering for terminal echo)."),
    },
    ["root"],
  ),
  "leaderboard": objectSchema(
    {
      root: stringParam("Project node id or slug. --project is accepted as an alias."),
      metric: stringParam('Metric dot-path to rank by (e.g. "metrics.val_loss").'),
      direction: stringParam("min (lower is better, default) or max (higher is better)."),
      cluster: stringParam("Optional run_cluster_key filter."),
      outcome: stringParam("Filter rows to one stored outcome before ranking."),
      columns: stringParam("Override the default title/<metric>/outcome/cluster/created_at column set."),
    },
    ["metric"],
  ),
  "hypothesis:add": objectSchema(
    {
      project_id: stringParam("Project the hypothesis belongs to."),
      claim: stringParam("The falsifiable claim, one sentence."),
      rationale: stringParam("Why you believe this might be true."),
      assumptions: stringParam("Comma-separated assumptions the claim rests on."),
      expected_observations: stringParam("Comma-separated observations that would support the claim."),
      disconfirmers: stringParam("Comma-separated observations that would kill the claim."),
      status: stringParam("proposed (default) | testing | supported | weakened | rejected."),
    },
    ["project_id", "claim"],
  ),
  "hypothesis:update": objectSchema(
    {
      node_id: stringParam("Hypothesis node id or slug."),
      status: stringParam("proposed | testing | supported | weakened | rejected."),
      because: stringParam("Comma-separated node ids/slugs (runs, evidence) that justify the change."),
      note: stringParam("One-line justification appended to the hypothesis body."),
    },
    ["node_id", "status"],
  ),
  "experiment:plan": objectSchema(
    {
      project_id: stringParam("Project the experiment belongs to."),
      hypothesis_id: stringParam("Hypothesis node this experiment tests (id or slug)."),
      title: stringParam("Plan title."),
      config: stringParam("Planned config as a JSON object or @file.json."),
      metric: stringParam('Primary metric dot-path (e.g. "metrics.val_loss").'),
      success_criterion: stringParam('Pass condition runs are judged against (e.g. "metrics.val_loss < 2.0").'),
      expected_result: stringParam("What you expect to observe if the hypothesis holds."),
      risks: stringParam("Comma-separated risks / likely failure modes."),
      run_cluster_key: stringParam("Cluster key runs of this plan inherit (generated from the title when omitted)."),
    },
    ["project_id", "hypothesis_id"],
  ),
  "decision:add": objectSchema(
    {
      project_id: stringParam("Project the decision belongs to."),
      decision: stringParam("The decision, one sentence."),
      alternatives: stringParam("Comma-separated alternatives that were considered."),
      basis: stringParam("Comma-separated node ids/slugs (runs, evidence, hypotheses) the decision rests on."),
      confidence: stringParam("low | medium (default) | high."),
      reversible: boolParam("Whether the decision can be cheaply reversed (default true)."),
    },
    ["project_id", "decision"],
  ),
  "eval:define": objectSchema(
    {
      project_id: stringParam("Project the eval belongs to."),
      name: stringParam("Eval name (e.g. cifar10-val)."),
      metric: stringParam('Metric dot-path runs report (e.g. "metrics.val_loss").'),
      direction: stringParam("min (lower is better) or max (higher is better)."),
      threshold: stringParam("Optional pass threshold for the metric."),
      dataset_ref: stringParam("Optional dataset reference (URL, path, or library source id)."),
    },
    ["project_id", "name", "metric", "direction"],
  ),
  "brief": objectSchema(
    {
      project_id: stringParam("Project node id or slug. --project is accepted as an alias."),
      full: boolParam("Raise the per-section caps for a deeper packet."),
    },
    ["project_id"],
  ),
  "reproduce": objectSchema(
    {
      node_id: stringParam("Run/result node id or slug to package. --node is accepted as an alias."),
      check: boolParam("Fail with the list of missing pieces when the packet is incomplete."),
    },
    ["node_id"],
  ),
  "run:record": objectSchema(
    {
      project_id: stringParam("Parent project node id; the run becomes its empirical child."),
      title: stringParam("Run title; derived from config.experiment/task/model/name when omitted."),
      config_json: stringParam("Run config as a JSON object or @file.json path."),
      metrics_json: stringParam("Numeric metrics as a JSON object or @file.json path."),
      stdout_tail: stringParam("Tail of stdout (will be secret-scrubbed before store)."),
      exit_code: intParam("Process exit code; outcome is inferred when not given explicitly."),
      outcome: stringParam("success | failure | inconclusive (defaults inferred from exit_code)."),
      failure_mode: stringParam("diverged | oom | data_bug | code_bug | underperformed | other."),
      run_cluster_key: stringParam("Stable key for folding repeats of the same experiment into one node."),
      plan_id: stringParam("experiment:plan node this run executes (id or slug); enables criterion_met + cluster inheritance."),
      hypothesis_id: stringParam("Hypothesis node this run tests, when there is no plan (id or slug)."),
      parent_run_id: stringParam("Run/node this run descends from (id or slug); carries optimizer candidate lineage. --parent-run is accepted as an alias."),
      candidate_idx: intParam("Optimizer-assigned candidate index."),
      scorecard_json: stringParam("evaluation_v1 per-example scorecard as a JSON object or @file.json path ({metric, items:[{ref,score,pass}], aggregate})."),
      eval: stringParam("Path to an EVAL.md-style results doc to attach as the run's results-first body. Auto-detected from EVAL.md / .atlas/EVAL.md in the cwd when omitted."),
      no_eval: boolParam("Do not auto-attach an EVAL.md results doc."),
      no_git: boolParam("Skip the automatic git code-state capture (repo/branch/commit are auto-detected from the cwd by default)."),
      payload_json: stringParam("Full body as a JSON object or @file.json path; inline flags override its fields."),
    },
    [],
  ),
  "run:chart": objectSchema(
    {
      project_id: stringParam("Project/control node whose runs are charted. --project is accepted as an alias."),
      metric: stringParam("Dot-path of the charted metric (e.g. metrics.score)."),
      direction: stringParam("max | min — which way 'better' points for the best-so-far line (default max)."),
      cluster: stringParam("Only chart runs with this run_cluster_key."),
      out: stringParam("Write the vega-lite spec to this path instead of a temp file."),
      no_attach: boolParam("Skip attaching the chart to the project node as a vega evidence artifact (attach is the default)."),
      title: stringParam("Chart title (defaults to 'score progression')."),
    },
    ["project_id"],
  ),
  "optimize:start": objectSchema(
    {
      target: stringParam("Repo-relative path to the artifact GEPA mutates (prompt/config/code file)."),
      benchmark: stringParam("Shell command that evaluates a candidate; {target} is substituted with the candidate path."),
      metric: stringParam("max | min (default max)."),
      objective: stringParam("One sentence describing what 'better' means; GEPA reflects on it."),
      background: stringParam("Extra domain context for GEPA's reflector."),
      max_metric_calls: intParam("Evaluation budget for the run (default 50)."),
      max_seconds: intParam("Wall-clock budget in seconds; stops at the next iteration boundary past the deadline (0 = no time limit). Composes with --max-metric-calls; first to hit wins."),
      stall: intParam("Consecutive non-improving iterations before stopping (default 5)."),
      parallel: intParam("Concurrent candidate evaluations (default 1). Values > 1 install a pinned gepa build with parallel proposal pipelines."),
      search_seeds: stringParam("Comma-separated ATLAS_EVAL_SEED values to repeat for each candidate during search (e.g. 0,1,2)."),
      search_aggregation: stringParam("How repeated search scores collapse before GEPA sees them: conservative (default), mean, or median."),
      reflection_lm: stringParam("Reflection model string (e.g. anthropic/claude-opus-4-7); defaults to GEPA's default."),
      gate: stringParam("Gate command(s); exit 0 = pass. Repeatable via comma-separated list. Failing candidates score worst."),
      project: stringParam("Existing project/control node to file the run under (id or slug)."),
      resume: stringParam("Existing optimize control node to resume (id or slug)."),
      ground: boolParam("Web-grounded reflection: search the web when the search stalls and fold relevant results into GEPA's reflection prompt (default off)."),
      require_grounding: boolParam("Preflight web search before spending evaluation budget when --ground is enabled (default true)."),
      ground_every: intParam("Also consult web search every N scored evaluations, not just on stall (default 0 = stall-only)."),
      ground_max: intParam("Maximum web-search consults per run (default 3)."),
      label: stringParam("Human label for the run (control node title)."),
      benchmark_timeout: intParam("Per-candidate benchmark timeout in seconds (default 900)."),
    },
    ["target", "benchmark", "objective"],
  ),
  "optimize:status": objectSchema(
    {
      node_id: stringParam("Optimize control node (id or slug). --node is accepted as an alias."),
    },
    ["node_id"],
  ),
  "optimize:stop": objectSchema(
    {
      node_id: stringParam("Optimize control node (id or slug). Writes gepa.stop into the run's run_dir on this machine."),
    },
    ["node_id"],
  ),
  "optimize:verify": objectSchema(
    {
      node_id: stringParam("Candidate node to verify, or a control node (verifies its best candidate). --node is accepted as an alias."),
      benchmark: stringParam("Shell command that evaluates the candidate; {target}/{worktree} are substituted. ATLAS_EVAL_SEED is exported per replication."),
      metric: stringParam("max | min (default max); sets the t-test direction."),
      seeds: intParam("Number of replications (default 10)."),
      threshold: stringParam("Success criterion the mean must beat; enables the one-sided t-test."),
      alpha: stringParam("Significance level for the verdict (default 0.01)."),
      gate: stringParam("Gate command(s) run per seed; exit 0 = pass. Comma-separated for multiple."),
      cluster: stringParam("run_cluster_key for the replications (default verify/<candidate>)."),
      project: stringParam("Node to record replications + the referee report under (default: the candidate's control node)."),
      target: stringParam("Repo-relative artifact path when the benchmark command uses {target}."),
      benchmark_timeout: intParam("Per-replication timeout in seconds (default 900)."),
    },
    ["node_id", "benchmark"],
  ),
  autoresearch: objectSchema(
    {
      goal: stringParam('One sentence: what "better" means (e.g. "reduce val_bpb in a fixed budget", "raise eval accuracy"). The only required input.'),
      path: stringParam("Repo path to research (default: the current directory — your fork). Also accepted as a bare positional argument."),
      target: stringParam("Repo-relative artifact file the search mutates (auto-detected from the repo when omitted)."),
      benchmark: stringParam("Explicit benchmark command emitting the contract JSON; {target} is substituted. When omitted, autoresearch generates .atlas/benchmark.sh from the repo."),
      metric: stringParam("max | min — inferred from the goal verb when omitted (lower/reduce/minimize → min; raise/improve/beat → max)."),
      budget: stringParam('Wall-clock budget like "8h", "30m", "90s" — "run it overnight" autonomy. Alternative to --max-metric-calls.'),
      max_metric_calls: intParam("Evaluation budget (default 50). Ignored when --budget is set as the primary cap."),
      seeds: intParam("Referee replications for the baseline and the winner (default 10)."),
      alpha: stringParam("Significance level for the verified verdict (default 0.05)."),
      parallel: intParam("Concurrent candidate evaluations during search (default 1)."),
      stall: intParam("Consecutive non-improving iterations before search stops (default 5)."),
      gate: stringParam("Extra Goodhart gate command(s) added to the generated files-unchanged gate; exit 0 = pass. Comma-separated for multiple."),
      ground: boolParam("Web-grounded reflection: search for relevant external work when the search stalls."),
      reflection_lm: stringParam("Reflection model string (e.g. anthropic/claude-opus-4-7); defaults to GEPA's default."),
      search_seeds: stringParam("Comma-separated ATLAS_EVAL_SEED values to repeat per candidate during search (for noisy benchmarks)."),
      search_aggregation: stringParam("How repeated search scores collapse before GEPA sees them: conservative (default), mean, or median."),
      project: stringParam("Existing project/control node to file the campaign under (id or slug). Defaults to find-or-create for this repo."),
      resume: stringParam("Resume a prior campaign from its control node (id or slug)."),
      benchmark_timeout: intParam("Per-evaluation benchmark timeout in seconds (default 900)."),
      scaffold_only: boolParam("Generate the benchmark scaffold (.atlas/benchmark.sh + score + gate) and stop, without running the campaign."),
      dry_run: boolParam("Preview the resolved plan (target, benchmark, baseline, pre-registration, budget) and exit without spending budget."),
      yes: boolParam("Skip the confirmation prompt and proceed (agent / non-interactive mode)."),
    },
    ["goal"],
  ),
  "note:add": objectSchema(
    {
      project_id: stringParam("Parent project node id; the note becomes an insight child of it."),
      text: stringParam("Note body (or @file.md path). First line becomes the title if --title is missing."),
      title: stringParam("Optional explicit title; defaults to the first line of --text."),
    },
    ["project_id", "text"],
  ),
  "notebook:cell": objectSchema(
    {
      project_id: stringParam("Parent project node id."),
      cell_id: stringParam("Notebook cell id (used in the auto title and config)."),
      notebook: stringParam("Notebook path or label for downstream cross-reference."),
      source: stringParam("Cell source (or @file path)."),
      output: stringParam("Cell stdout/output (or @file path); becomes the scrubbed stdout_tail."),
      title: stringParam("Override the derived title."),
      outcome: stringParam("success | failure | inconclusive (defaults success unless --errored)."),
      errored: boolParam("Mark the cell as errored; outcome becomes failure unless overridden."),
      run_cluster_key: stringParam("Cluster key (e.g. a notebook path) for folding repeats."),
    },
    ["project_id"],
  ),
};

const GROUPS = {
  "program:snapshot": "map",
};

function groupFor(name) {
  if (GROUPS[name]) return GROUPS[name];
  if (name.startsWith("node:") || name.startsWith("map:") || name.startsWith("link:") || name.startsWith("access:") || name.startsWith("draft:") || name.startsWith("label:") || name.startsWith("project:")) return "map";
  if (name.startsWith("evidence:")) return "evidence";
  if (name.startsWith("run:") || name === "leaderboard") return "runs";
  if (name.startsWith("optimize:") || name === "autoresearch") return "optimize";
  if (
    name.startsWith("hypothesis:") ||
    name.startsWith("experiment:") ||
    name.startsWith("decision:") ||
    name.startsWith("eval:") ||
    name === "brief" ||
    name === "reproduce"
  ) {
    return "research-loop";
  }
  if (name.startsWith("history:")) return "map";
  if (name === "fork") return "map";
  if (name.startsWith("ops:")) return "ops";
  if (name.startsWith("github:") || name.startsWith("integration:") || name.startsWith("repo:")) return "integrations";
  if (name.startsWith("key:")) return "keys";
  if (name.startsWith("agent:")) return "agent";
  if (name.startsWith("secret:") || ["login", "logout", "whoami", "doctor"].includes(name)) return "auth";
  if (name.startsWith("config:")) return "config";
  if (name.startsWith("account:")) return "account";
  if (name.startsWith("web:")) return "web";
  if (name.startsWith("usage:")) return "usage";
  if (name === "init") return "setup";
  if (name === "note:add" || name === "notebook:cell" || name.startsWith("log:")) return "journal";
  return "other";
}

function defaultSchema({ pathParams = [], queryParams = [], bodyParams = [], bodyMode = "auto" } = {}) {
  const properties = {};
  const required = [...pathParams];
  const addString = (name, description) => {
    if (!name || properties[name]) return;
    properties[name] = stringParam(description);
  };
  for (const name of pathParams) addString(name, `${name} path parameter.`);
  for (const name of queryParams || []) addString(name, `${name} query parameter.`);
  for (const name of bodyParams || []) addString(name, `${name} body parameter.`);

  const requireBodyField = (name, description) => {
    addString(name, description);
    if (!required.includes(name)) required.push(name);
  };
  switch (bodyMode) {
    case "payload_json":
      requireBodyField("payload_json", "JSON request payload.");
      break;
    case "payload":
      requireBodyField("payload", "JSON request payload.");
      break;
    case "node_ids":
      requireBodyField("node_ids", "Comma-separated node IDs.");
      break;
    case "node_delete_bulk":
      requireBodyField("node_ids", "Comma-separated node IDs.");
      break;
    case "merge":
      requireBodyField("node_ids", "Comma-separated node IDs.");
      break;
    case "tag_assign":
      requireBodyField("tag_ids", "Comma-separated label IDs.");
      break;
    case "artifact_delete_bulk":
      requireBodyField("artifact_ids", "Comma-separated evidence IDs.");
      break;
    case "artifact_upload":
      properties.items = { type: "array", description: "Evidence upload items." };
      required.push("items");
      break;
    case "grep":
      requireBodyField("pattern", "Text pattern to search for.");
      break;
    case "search_query":
    case "document_query":
    case "research_query":
      requireBodyField("query", "Query text.");
      break;
    case "subgraph_export":
      requireBodyField("node_ids", "Comma-separated node IDs.");
      properties.include_descendants = boolParam("Include descendants of selected nodes.");
      properties.max_nodes = intParam("Maximum nodes to export.");
      break;
    case "huggingface_secret":
      addString("token", "Hugging Face access token.");
      addString("token_env", "Environment variable containing the Hugging Face access token.");
      break;
    case "wandb_secret":
      addString("api_key", "W&B API key.");
      addString("api_key_env", "Environment variable containing the W&B API key.");
      break;
  }
  return objectSchema(properties, [...new Set(required)]);
}

function schemaFor(name, defaults) {
  return SCHEMA_OVERRIDES[name] || BASE_SCHEMAS[name] || defaultSchema(defaults);
}

function spec({
  name,
  method,
  path,
  aliases = [],
  summary,
  pathParams = [],
  queryParams = null,
  bodyParams = null,
  bodyMode = "auto",
  raw = false,
  stream = false,
  binary = false,
  destructive = false,
  openUrl = false,
  local = false,
  public: isPublic = false,
  secretEnvArgs = {},
}) {
  const schema = schemaFor(name, { pathParams, queryParams, bodyParams, bodyMode });
  return {
    name,
    group: groupFor(name),
    method,
    path,
    aliases,
    summary: summary || name,
    description: summary || name,
    schema,
    pathParams,
    queryParams,
    bodyParams,
    bodyMode,
    raw,
    stream,
    binary,
    destructive,
    openUrl,
    local,
    public: isPublic,
    secretEnvArgs,
    endpoints: [`${method} ${path}`],
  };
}

export const COMMANDS = [
  spec({ name: "login", method: "LOCAL", path: "/auth/cli/browser/start", local: true, bodyParams: ["name"], summary: "Log in through the browser and store a Gateway API key." }),
  spec({ name: "logout", method: "LOCAL", path: "/auth/logout", local: true, summary: "Remove the stored Gateway API key for the active profile." }),
  spec({ name: "whoami", method: "GET", path: "/auth/status", summary: "Show the authenticated Gateway user." }),
  spec({ name: "doctor", method: "LOCAL", path: "/status", local: true, summary: "Check compatibility CLI config, auth, backend reachability, integrations, and the local spool." }),
  spec({ name: "init", method: "LOCAL", path: "/init", local: true, bodyParams: ["title", "path", "repo_url", "no_ambient", "no_log", "no_web", "web_mode", "capture_mode", "privacy", "run_command", "force"], summary: "Find-or-create the Gateway project for this repo and write atlas.json, the opt-in activation contract for ambient research behavior. Refuses to run in $HOME or a filesystem root (pass --force to override). Auto-detects a run command from common run scripts." }),
  spec({ name: "secret:set", method: "LOCAL", path: "/auth/keychain", local: true, summary: "Read a Gateway API key from stdin and store it in macOS Keychain for a profile." }),
  spec({ name: "secret:clear", method: "LOCAL", path: "/auth/keychain", local: true, summary: "Remove the macOS Keychain Gateway API key for a profile." }),
  spec({ name: "config:list", method: "LOCAL", path: "/profile", local: true, summary: "List local Gateway CLI profiles with secrets redacted." }),
  spec({ name: "config:show", method: "LOCAL", path: "/profile/{name}", local: true, bodyParams: ["name"], summary: "Show one local Gateway CLI profile with secrets redacted." }),
  spec({ name: "config:set", method: "LOCAL", path: "/profile/{name}", local: true, bodyParams: ["name", "base_url", "api_key_env", "default_format", "timeout_ms", "retry_max", "active"], summary: "Create or update a local Gateway CLI profile." }),
  spec({ name: "config:unset", method: "LOCAL", path: "/profile/{name}", local: true, bodyParams: ["name"], summary: "Remove a local Gateway CLI profile." }),
  spec({ name: "account:update", method: "PATCH", path: "/users/me", summary: "Update your Gateway account profile." }),
  spec({ name: "ops:maps:list", method: "GET", path: "/admin/graphs", queryParams: ["tag_id", "kind", "owner_user_id", "created_after", "created_before", "cursor", "page_size"], summary: "Admin-only list of map roots." }),
  spec({ name: "ops:maps:export", method: "GET", path: "/admin/graphs/{root_node_id}/export", pathParams: ["root_node_id"], queryParams: ["max_nodes"], summary: "Admin-only canonical export of one map." }),
  spec({ name: "ops:maps:export-stream", method: "GET", path: "/admin/graphs/export-stream", queryParams: ["tag_id", "kind", "owner_user_id", "created_after", "created_before", "cursor", "page_size", "max_nodes"], raw: true, stream: true, summary: "Admin-only NDJSON export of map roots." }),
  spec({ name: "program:snapshot", method: "GET", path: "/nodes/{node_id}/campaign/snapshot", pathParams: ["node_id"], summary: "Resolve the program root snapshot for a node." }),
  spec({ name: "map:view", method: "GET", path: "/graph", queryParams: ["node_id", "depth", "max_nodes", "page_size", "cursor", "filter", "exclude"], summary: "Read a structured research map projection." }),
  spec({ name: "link:add", method: "POST", path: "/nodes/{node_id}/parents/add", pathParams: ["node_id"], bodyParams: ["parent_id", "expected_revision", "expected_parent_revision"], summary: "Add a dependency link between nodes." }),
  spec({ name: "node:history", method: "GET", path: "/nodes/{node_id}/audit", pathParams: ["node_id"], queryParams: ["limit"], summary: "List history events for one node." }),
  spec({ name: "node:branch", method: "POST", path: "/nodes/{node_id}/branch", pathParams: ["node_id"], bodyParams: ["expected_revision", "title", "updated_by"], summary: "Create a branch node from an existing node." }),
  spec({ name: "link:children", method: "GET", path: "/nodes/{node_id}/children", pathParams: ["node_id"], summary: "List direct child links for one node." }),
  spec({ name: "node:save", method: "POST", path: "/nodes/{node_id}/commit", pathParams: ["node_id"], bodyMode: "payload_json", summary: "Save staged changes to an existing node.", aliases: ["nc"] }),
  spec({ name: "node:create", method: "POST", path: "/nodes/commit-new", bodyMode: "payload_json", summary: "Create and save a new node in one request.", aliases: ["ncn"] }),
  spec({ name: "repo:pin", method: "POST", path: "/repos/{node_id}/pin", pathParams: ["node_id"], bodyParams: ["sha", "tag"], summary: "Pin a node's commit as an immutable tag on its linked repo so the exact code state stays reachable (capture-by-value)." }),
  spec({ name: "repo:capture", method: "POST", path: "/repos/{node_id}/capture", pathParams: ["node_id"], bodyParams: ["repo_url", "branch_name", "head_commit_sha", "pin", "tag"], summary: "Record the code state (repo/branch/commit) behind a node and optionally pin it, so a public-graph viewer can open the exact code." }),
  spec({ name: "run:record", method: "LOCAL", path: "/runs:record", local: true, bodyParams: ["project_id", "title", "config_json", "metrics_json", "stdout_tail", "exit_code", "outcome", "failure_mode", "run_cluster_key", "plan_id", "hypothesis_id", "parent_run_id", "candidate_idx", "scorecard_json", "eval", "no_eval", "payload_json"], summary: "Flight Recorder: post a single run (config, metrics, stdout_tail, outcome) as an empirical node under the project. Bind it to an experiment:plan with --plan to get criterion_met evaluated; chain optimizer candidates with --parent-run; attach per-example results with --scorecard-json. Spools to ~/.atlas/spool/ when the backend is unreachable; pending entries flush on the next CLI invocation." }),
  spec({ name: "run:chart", method: "LOCAL", path: "/runs:chart", local: true, bodyParams: ["project_id", "metric", "direction", "cluster", "out", "no_attach", "title"], summary: "Build a score-progression chart (vega-lite) from the runs under a project and attach it to the project node as evidence. Points colored by outcome, best-so-far line, optimizer-ready. `atlas run:chart --project <id> --metric metrics.score`." }),
  spec({ name: "optimize:start", method: "LOCAL", path: "/optimize:start", local: true, bodyParams: ["target", "benchmark", "metric", "objective", "background", "max_metric_calls", "max_seconds", "stall", "parallel", "search_seeds", "search_aggregation", "reflection_lm", "gate", "project", "resume", "ground", "require_grounding", "ground_every", "ground_max", "label", "benchmark_timeout"], summary: "Run a GEPA optimization loop over an artifact (prompt/config/code) against a benchmark command, recording every candidate into the map with lineage, scorecards, and live progress. --parallel K evaluates K candidates concurrently; --search-seeds repeats each candidate before aggregation; --max-seconds sets a wall-clock budget; --resume continues a control node from its best recorded candidate. Wraps the bundled harness (requires `uv` + a reflection-LM key)." }),
  spec({ name: "optimize:status", method: "LOCAL", path: "/optimize:status", local: true, bodyParams: ["node_id"], summary: "Show an optimize run's live state from its control node: status, budget used, best score/candidate, stall, stop_reason." }),
  spec({ name: "optimize:stop", method: "LOCAL", path: "/optimize:stop", local: true, bodyParams: ["node_id"], summary: "Gracefully stop a running optimize loop started on this machine (writes gepa.stop into the run's run_dir; GEPA's FileStopper exits at the next iteration boundary)." }),
  spec({ name: "optimize:verify", method: "LOCAL", path: "/optimize:verify", local: true, bodyParams: ["node_id", "benchmark", "metric", "seeds", "threshold", "alpha", "gate", "cluster", "project", "target", "benchmark_timeout"], summary: "Referee a recorded candidate before claiming anything: re-run its benchmark N times at its exact commit (ATLAS_EVAL_SEED=0..N-1), record the replications as a run cluster, compute mean/std and a one-sided t-test against --threshold, and attach a referee-report node. `atlas optimize:verify --node <candidate> --benchmark \"…\" --seeds 10 --metric min --threshold 0.92`." }),
  spec({ name: "autoresearch", method: "LOCAL", path: "/autoresearch", local: true, bodyParams: ["goal", "path", "target", "benchmark", "metric", "budget", "max_metric_calls", "seeds", "alpha", "parallel", "stall", "gate", "ground", "reflection_lm", "search_seeds", "search_aggregation", "project", "resume", "benchmark_timeout", "scaffold_only", "dry_run", "yes"], summary: "One-command refereed research campaign over a forked repo: point it at your fork with a plain-English --goal and it auto-detects the artifact, generates a benchmark (.atlas/benchmark.sh, pristine by worktree isolation + a files-unchanged gate), measures the seed baseline, pre-registers a hypothesis + plan BEFORE the first candidate, runs the GEPA search, then referees BOTH the baseline and the winner over N seeds and prints `verified: <metric> X → Y (Δ, p<alpha, n)`. --dry-run previews; --scaffold-only stops after generating the benchmark; --budget 8h runs to a wall-clock cap. Wraps optimize:start/verify (requires `uv` + a reflection-LM key)." }),
  spec({ name: "optimize:progress", method: "POST", path: "/optimize:progress", bodyParams: ["node_id", "objective", "target", "metric", "status", "budget_total", "budget_used", "stall_limit", "best_score", "best_node_id", "pareto_size", "candidates_evaluated", "stop_reason", "run_dir"], summary: "Merge optimizer run state (budget, best score, stop_reason) into a control node's semantic_data. Used by the optimize harness / AtlasCallback; the web UI renders it as a live budget bar." }),
  spec({ name: "run:spool:list", method: "LOCAL", path: "/runs:spool", local: true, summary: "List Flight Recorder entries queued in ~/.atlas/spool/ (oldest first)." }),
  spec({ name: "run:spool:flush", method: "LOCAL", path: "/runs:spool/flush", local: true, summary: "Best-effort replay every queued Flight Recorder entry against the backend. Successful posts are deleted from the spool; failures remain for the next call." }),
  spec({ name: "run:spool:clear", method: "LOCAL", path: "/runs:spool/clear", local: true, bodyParams: ["yes"], destructive: true, summary: "Delete every queued Flight Recorder entry without posting. Useful for stale entries from older broken installs." }),
  spec({ name: "run:compare", method: "GET", path: "/runs:compare", queryParams: ["root", "cluster", "columns", "outcome", "sort", "direction", "best", "format"], summary: "Render a comparison matrix across the runs under a project. Dot-paths into the captured run data (config.lr, metrics.val_loss) supported as columns; --cluster filters to one run_cluster_key; --sort/--direction order rows and --best marks the winner; --format=table returns a markdown rendering for terminal echo." }),
  spec({ name: "leaderboard", method: "LOCAL", path: "/runs:leaderboard", local: true, bodyParams: ["root", "metric", "direction", "cluster", "outcome", "columns"], summary: "Rank the runs under a project by one metric (a run:compare preset: sorted in the metric's better direction with the best row marked). `atlas leaderboard --project <id> --metric metrics.val_loss`." }),
  spec({ name: "hypothesis:add", method: "POST", path: "/hypotheses:add", bodyParams: ["project_id", "claim", "rationale", "assumptions", "expected_observations", "disconfirmers", "status"], summary: "Pose a hypothesis as a first-class node under the project: the claim, why you believe it, what would confirm it, and what would kill it." }),
  spec({ name: "hypothesis:update", method: "POST", path: "/hypotheses:update", bodyParams: ["node_id", "status", "because", "note"], summary: "Move a hypothesis through its lifecycle (proposed -> testing -> supported / weakened / rejected), citing the run/evidence nodes that justify the change." }),
  spec({ name: "experiment:plan", method: "POST", path: "/experiments:plan", bodyParams: ["project_id", "hypothesis_id", "title", "config", "metric", "success_criterion", "expected_result", "risks", "run_cluster_key"], summary: "Declare what an experiment will test before running it: the hypothesis it tests, the config, the metric, and the success criterion runs are judged against. Pre-allocates the run_cluster_key that run:record inherits." }),
  spec({ name: "decision:add", method: "POST", path: "/decisions:add", bodyParams: ["project_id", "decision", "alternatives", "basis", "confidence", "reversible"], summary: "Record a research decision and link the runs/evidence/hypotheses it rests on, so `map:lineage` answers \"why did we do this?\" later." }),
  spec({ name: "eval:define", method: "POST", path: "/evals:define", bodyParams: ["project_id", "name", "metric", "direction", "threshold", "dataset_ref"], summary: "Define a reusable evaluation: the metric dot-path, which direction is better, and an optional threshold. Bind runs to it via experiment:plan / leaderboard." }),
  spec({ name: "brief", method: "GET", path: "/projects/{project_id}/brief", pathParams: ["project_id"], queryParams: ["full"], summary: "The project context packet for agents: open hypotheses, recent runs, failure clusters, decisions, open branches, and suggested next actions. Start every session with this." }),
  spec({ name: "reproduce", method: "LOCAL", path: "/reproduce", local: true, bodyParams: ["node_id", "check"], summary: "Assemble a reproducibility packet for a run/result node: exact config, captured code state (repo/commit/pin), dataset ref, and success criterion. --check fails when the packet is incomplete." }),
  spec({ name: "note:add", method: "LOCAL", path: "/notes", local: true, bodyParams: ["project_id", "text", "title"], summary: "Add a freeform note to a project as an insight node. Same surface humans use in Journal; agents reach for this when the thing to record isn't an experiment run." }),
  spec({ name: "notebook:cell", method: "LOCAL", path: "/notebook/cell", local: true, bodyParams: ["project_id", "cell_id", "notebook", "source", "output", "title", "outcome", "errored", "run_cluster_key"], summary: "Capture a notebook cell + its output as an empirical node. Thin wrapper over runs:record with cell-shaped defaults; same spool semantics." }),
  spec({ name: "log:append", method: "LOCAL", path: "/research/log", local: true, bodyParams: ["project_id", "entry_type", "title", "body", "refs_json", "payload_json"], summary: "Append a lightweight event to the project's research log. Uses atlas.json for --project when available and spools locally when offline." }),
  spec({ name: "log:tail", method: "GET", path: "/research/log", queryParams: ["project_id", "entry_types", "since", "limit"], summary: "Read recent project research-log entries, newest first." }),
  spec({ name: "log:search", method: "POST", path: "/research/log/search", bodyParams: ["project_id", "query", "limit"], summary: "Search the project research log by title/body text." }),
  spec({ name: "draft:create", method: "POST", path: "/nodes", bodyParams: ["title"], summary: "Create a draft node shell." }),
  spec({ name: "node:delete", method: "DELETE", path: "/nodes/{node_id}", pathParams: ["node_id"], queryParams: ["delete_mode"], destructive: true, summary: "Delete a node." }),
  spec({ name: "node:delete-bulk", method: "POST", path: "/nodes/bulk-delete", bodyMode: "node_delete_bulk", destructive: true, summary: "Delete multiple nodes." }),
  spec({ name: "node:files", method: "GET", path: "/nodes/{node_id}/files", pathParams: ["node_id"], summary: "List evidence files for one node." }),
  spec({ name: "node:show", method: "GET", path: "/nodes/{node_id}", pathParams: ["node_id"], queryParams: ["projection"], summary: "Show one node." }),
  spec({ name: "node:list", method: "GET", path: "/nodes", queryParams: ["per_page", "page", "cursor", "limit", "kind", "visibility"], summary: "List visible nodes." }),
  spec({ name: "project:list", method: "LOCAL", path: "/projects", local: true, bodyParams: ["limit"], summary: "List project-root nodes you can use as a --project. Filters /nodes locally to the top-level / project-kind entries so you can find a parent without paging the full map." }),
  spec({ name: "project:create", method: "LOCAL", path: "/projects/create", local: true, bodyParams: ["title", "path", "repo_url"], summary: "Find-or-create the project root for the current folder/repo (dedupe-key aware). Returns the existing project when one matches instead of minting a duplicate; the canonical way to bootstrap before run:record / note:add." }),
  spec({ name: "project:merge", method: "LOCAL", path: "/projects/merge", local: true, bodyParams: ["canonical", "absorb", "yes"], destructive: true, summary: "Collapse duplicate project roots into a canonical one. Re-parents children, backfills dedupe_key, deletes the absorbed roots. Use to clean up pre-dedupe-key duplicate `Project: <folder>` nodes." }),
  spec({ name: "fork", method: "LOCAL", path: "/fork", local: true, bodyParams: ["node_id", "include_descendants", "max_nodes", "title"], summary: "Fork any visible node/subtree into your account as a new private graph, preserving code-state and provenance so you can continue from it." }),
  spec({ name: "node:merge", method: "POST", path: "/nodes/merge", bodyMode: "merge", summary: "Merge nodes into a resolved node." }),
  spec({ name: "link:parents", method: "GET", path: "/nodes/{node_id}/parents", pathParams: ["node_id"], summary: "List direct parent links for one node." }),
  spec({ name: "link:remove", method: "POST", path: "/nodes/{node_id}/parents/remove", pathParams: ["node_id"], bodyParams: ["parent_id", "expected_revision", "expected_parent_revision"], summary: "Remove a dependency link between nodes." }),
  spec({ name: "map:lineage", method: "GET", path: "/nodes/{node_id}/ancestry", pathParams: ["node_id"], queryParams: ["projection", "max_depth"], summary: "Render node lineage." }),
  spec({ name: "map:summary", method: "GET", path: "/nodes/{node_id}/summary", pathParams: ["node_id"], queryParams: ["max_nodes"], summary: "Render a map summary." }),
  spec({ name: "map:tree", method: "GET", path: "/nodes/{node_id}/tree", pathParams: ["node_id"], queryParams: ["projection", "max_nodes", "max_depth"], summary: "Render a map tree." }),
  spec({ name: "node:resolve", method: "GET", path: "/nodes/resolve-by-slug", queryParams: ["slug_name", "context_node_id"], summary: "Resolve a node slug." }),
  spec({ name: "access:show", method: "GET", path: "/nodes/{node_id}/access-policy", pathParams: ["node_id"], summary: "Show a node access policy." }),
  spec({ name: "access:set", method: "PUT", path: "/nodes/{node_id}/access-policy", pathParams: ["node_id"], summary: "Set a node access policy." }),
  spec({ name: "node:share", method: "LOCAL", path: "/nodes/share", local: true, bodyParams: ["node_id", "visibility"], summary: "Set a node's visibility (private | unlisted | public) and print the canonical web URL. Thin ergonomic wrapper over access:set so scripts can publish from the CLI." }),
  spec({ name: "access:set-bulk", method: "POST", path: "/nodes/access-policy/bulk", bodyParams: ["node_ids", "visibility", "principal_type", "principal_id", "access_level", "expected_revision_by_node"], summary: "Set access policy on multiple nodes." }),
  spec({ name: "access:summaries", method: "POST", path: "/nodes/access-policy/summaries", bodyParams: ["node_ids"], summary: "Get access summaries for multiple nodes." }),
  spec({ name: "draft:lock", method: "POST", path: "/nodes/{node_id}/stage/lease/acquire", pathParams: ["node_id"], bodyParams: ["base_committed_revision", "expected_revision", "stage_session_id", "ttl_seconds", "purpose"], summary: "Lock a draft for coordinated editing." }),
  spec({ name: "draft:derive-hypothesis", method: "POST", path: "/nodes/{node_id}/stage/backfill/hypothesis", pathParams: ["node_id"], bodyParams: ["expected_revision", "force"], summary: "Derive a staged hypothesis from draft content." }),
  spec({ name: "draft:derive-insights", method: "POST", path: "/nodes/{node_id}/stage/backfill/insights", pathParams: ["node_id"], bodyParams: ["expected_revision", "force"], summary: "Derive staged insights from draft content." }),
  spec({ name: "draft:renew", method: "POST", path: "/nodes/{node_id}/stage/lease/heartbeat", pathParams: ["node_id"], bodyParams: ["stage_session_id", "ttl_seconds"], summary: "Renew a draft edit lock." }),
  spec({ name: "draft:unlock", method: "POST", path: "/nodes/{node_id}/stage/lease/release", pathParams: ["node_id"], bodyParams: ["stage_session_id", "reason"], summary: "Unlock a draft edit session." }),
  spec({ name: "evidence:refresh", method: "POST", path: "/nodes/{node_id}/remote-artifacts/refresh", pathParams: ["node_id"], bodyParams: ["remote_artifact_id", "title", "url", "rows_path", "row_id", "cache_ttl_seconds"], summary: "Refresh linked public HTTPS JSON evidence." }),
  spec({ name: "evidence:link", method: "POST", path: "/nodes/{node_id}/remote-artifacts/resolve", pathParams: ["node_id"], bodyParams: ["remote_artifact_id", "title", "url", "rows_path", "row_id", "cache_ttl_seconds", "force_refresh"], summary: "Link public HTTPS JSON evidence to a node." }),
  spec({ name: "label:assign", method: "PUT", path: "/nodes/{node_id}/tags", pathParams: ["node_id"], bodyMode: "tag_assign", summary: "Assign labels to a node." }),
  spec({ name: "label:create", method: "POST", path: "/nodes/{root_node_id}/tags", pathParams: ["root_node_id"], bodyParams: ["name", "bg_color", "text_color", "expected_revision", "one_only", "track_history"], summary: "Create a reusable map label." }),
  spec({ name: "label:delete", method: "DELETE", path: "/nodes/{root_node_id}/tags/{tag_id}", pathParams: ["root_node_id", "tag_id"], bodyParams: ["expected_revision"], destructive: true, summary: "Delete a reusable map label." }),
  spec({ name: "label:update", method: "PATCH", path: "/nodes/{root_node_id}/tags/{tag_id}", pathParams: ["root_node_id", "tag_id"], bodyParams: ["name", "bg_color", "text_color", "expected_revision", "one_only", "track_history"], summary: "Update a reusable map label." }),
  spec({ name: "evidence:delete", method: "DELETE", path: "/nodes/{node_id}/artifacts/{artifact_id}", pathParams: ["node_id", "artifact_id"], bodyParams: ["expected_revision"], destructive: true, summary: "Delete evidence." }),
  spec({ name: "evidence:delete-bulk", method: "POST", path: "/nodes/{node_id}/artifacts/bulk-delete", pathParams: ["node_id"], bodyMode: "artifact_delete_bulk", destructive: true, summary: "Delete multiple evidence items from one node." }),
  spec({ name: "evidence:show", method: "GET", path: "/nodes/{node_id}/artifacts/{artifact_id}", pathParams: ["node_id", "artifact_id"], summary: "Show one evidence item." }),
  spec({ name: "evidence:list", method: "GET", path: "/nodes/{node_id}/artifacts", pathParams: ["node_id"], summary: "List evidence attached to one node." }),
  spec({ name: "evidence:note", method: "PATCH", path: "/nodes/{node_id}/artifacts/{artifact_id}/note", pathParams: ["node_id", "artifact_id"], bodyParams: ["expected_revision", "note"], summary: "Add, update, or clear an evidence note." }),
  spec({ name: "evidence:add", method: "POST", path: "/nodes/{node_id}/artifacts/uploads/prepare", pathParams: ["node_id"], bodyMode: "artifact_upload", summary: "Add local evidence in one prepare-upload-finalize flow.", aliases: ["aru"] }),
  spec({ name: "evidence:finalize", method: "POST", path: "/nodes/{node_id}/artifacts/uploads/finalize", pathParams: ["node_id"], bodyParams: ["batch_token"], summary: "Finalize a prepared evidence upload batch." }),
  spec({ name: "evidence:prepare", method: "POST", path: "/nodes/{node_id}/artifacts/uploads/prepare", pathParams: ["node_id"], bodyParams: ["expected_revision", "items"], summary: "Prepare an evidence upload batch." }),
  spec({ name: "evidence:download", method: "GET", path: "/blobs", queryParams: ["storage_path"], raw: true, binary: true, summary: "Download raw evidence bytes by storage path." }),
  spec({ name: "evidence:files", method: "GET", path: "/users/me/files", queryParams: ["page", "page_size"], summary: "List all evidence files owned by the current user." }),
  spec({ name: "history:export", method: "GET", path: "/legacy/history/export.jsonl", raw: true, summary: "Export map history as JSONL." }),
  spec({ name: "map:export", method: "POST", path: "/export", bodyMode: "subgraph_export", summary: "Export a map subset." }),
  spec({ name: "map:summary:export", method: "POST", path: "/export-summary", bodyMode: "node_ids", summary: "Export a Markdown map summary." }),
  spec({ name: "map:summary:pdf", method: "POST", path: "/export-summary-pdf", bodyMode: "node_ids", raw: true, binary: true, summary: "Export a map summary PDF." }),
  spec({ name: "map:summary:render-pdf", method: "POST", path: "/export-summary-render-pdf", bodyMode: "node_ids", raw: true, binary: true, summary: "Render a map summary PDF." }),
  spec({ name: "map:summary:stream", method: "POST", path: "/export-summary-stream", bodyMode: "node_ids", raw: true, stream: true, summary: "Stream a map summary." }),
  spec({ name: "map:import", method: "POST", path: "/import", bodyMode: "payload", summary: "Import a compatible map subset." }),
  spec({ name: "github:disconnect", method: "DELETE", path: "/auth/github/disconnect", destructive: true, summary: "Disconnect GitHub." }),
  spec({ name: "github:set", method: "POST", path: "/auth/github/pat", bodyMode: "github_secret", secretEnvArgs: { token_env: "token" }, summary: "Connect GitHub from the CLI with a personal access token (durable 'Code sync'); enables repo:pin / repo:capture." }),
  spec({ name: "github:link", method: "GET", path: "/auth/github/install-url", openUrl: true, summary: "Print the web URL to connect GitHub in the browser (fallback to github:set for CLI-only setup)." }),
  spec({ name: "github:reconnect", method: "GET", path: "/auth/github/install-url", openUrl: true, aliases: ["github:refresh"], summary: "Reopen the GitHub install URL to refresh / renew an expired token. Same backend route as github:link; named differently so `atlas doctor`'s expired-token nudge has an obvious follow-up command." }),
  spec({ name: "github:refresh-repos", method: "POST", path: "/auth/github/refresh-repos", summary: "Refresh accessible GitHub repositories." }),
  spec({ name: "github:status", method: "GET", path: "/auth/github/status", summary: "Show GitHub integration status." }),
  spec({ name: "integration:huggingface:remove", method: "DELETE", path: "/auth/integrations/huggingface", destructive: true, summary: "Remove Hugging Face integration." }),
  spec({ name: "integration:huggingface:set", method: "PUT", path: "/auth/integrations/huggingface", bodyMode: "huggingface_secret", secretEnvArgs: { token_env: "token" }, summary: "Store a Hugging Face access token." }),
  spec({ name: "integration:status", method: "GET", path: "/auth/integrations/status", summary: "Show integration status." }),
  spec({ name: "integration:wandb:remove", method: "DELETE", path: "/auth/integrations/wandb", destructive: true, summary: "Remove W&B integration." }),
  spec({ name: "integration:wandb:set", method: "PUT", path: "/auth/integrations/wandb", bodyMode: "wandb_secret", secretEnvArgs: { api_key_env: "api_key" }, summary: "Store a W&B API key." }),
  spec({ name: "key:create", method: "POST", path: "/auth/api-keys", summary: "Create a Gateway API key." }),
  spec({ name: "key:delete", method: "DELETE", path: "/auth/api-keys/{key_id}", pathParams: ["key_id"], destructive: true, summary: "Delete a Gateway API key." }),
  spec({ name: "key:list", method: "GET", path: "/auth/api-keys", queryParams: ["limit", "offset"], summary: "List Gateway API keys." }),
  spec({ name: "key:rotate", method: "POST", path: "/auth/api-keys/{key_id}/rotate", pathParams: ["key_id"], bodyParams: ["expiry_days"], destructive: true, summary: "Rotate a Gateway API key." }),
  // ── Discovery (public; no API key required) ──────────────────────────
  spec({ name: "explore", method: "GET", path: "/explore", queryParams: ["query", "sort", "page", "per_page"], public: true, summary: "Browse the public Gateway archive of research graphs (authors, stars, forks, papers). Add --query to search, --sort=trending|top|forks|new." }),
  spec({ name: "researchers", method: "GET", path: "/researchers", queryParams: ["query", "sort", "page", "per_page"], public: true, summary: "Browse public researchers (people with >=1 public graph). Add --query to search by handle or name." }),
  spec({ name: "competitions", aliases: ["comps"], method: "GET", path: "/competitions", public: true, summary: "List open research competitions with graph-backed leaderboards." }),
  spec({ name: "competition", aliases: ["comp"], method: "GET", path: "/competitions/{slug}", pathParams: ["slug"], public: true, summary: "Show a competition and its full leaderboard. e.g. `atlas competition parameter-golf`." }),
  spec({ name: "web:search", method: "POST", path: "/web/search", bodyMode: "web_search", bodyParams: ["query", "project_id", "num_results", "top_k", "category", "search_type", "log"], summary: "Run Gateway's metered general web search. In atlas.json projects, agents can use this as a provenance-capturing WebSearch alternative." }),
  spec({ name: "web:fetch", method: "POST", path: "/web/fetch", bodyMode: "web_fetch", bodyParams: ["url", "project_id", "with_summary", "text_limit", "log"], summary: "Fetch and extract a URL through Gateway's metered web layer, optionally logging the source to the project research log." }),
  spec({ name: "usage:summary", method: "GET", path: "/usage/summary", summary: "Show compatibility-route usage summary." }),
];

// ---------------------------------------------------------------------------
// Legacy aliases (pre-0.8 names)
//
// 0.8.0 normalized the registry to the conventions in cli/CONVENTIONS.md:
// singular namespaces (node:, label:, key:, …) and `run:` for the Flight
// Recorder. Every retained pre-0.8 name keeps working as an alias so published
// skills, scripts, and muscle memory don't break.
// ---------------------------------------------------------------------------

const LEGACY_PREFIXES = [
  ["integration:", "integrations:"],
  ["secret:", "secrets:"],
  ["label:", "labels:"],
  ["node:", "nodes:"],
  ["key:", "keys:"],
  ["run:", "runs:"],
];

const LEGACY_NAMES = {
  "project:merge": "projects:merge",
};

export function legacyAliasFor(name) {
  if (LEGACY_NAMES[name]) return LEGACY_NAMES[name];
  for (const [current, legacy] of LEGACY_PREFIXES) {
    if (name.startsWith(current)) return legacy + name.slice(current.length);
  }
  return null;
}

for (const command of COMMANDS) {
  const legacy = legacyAliasFor(command.name);
  if (legacy && !command.aliases.includes(legacy)) command.aliases.push(legacy);
}

export const COMMAND_BY_NAME = new Map();
for (const command of COMMANDS) {
  COMMAND_BY_NAME.set(command.name, command);
  for (const alias of command.aliases) COMMAND_BY_NAME.set(alias, command);
}

export function getCommand(name) {
  return COMMAND_BY_NAME.get(name) || null;
}

export function resolveAlias(name) {
  return COMMAND_BY_NAME.get(name)?.name || name;
}

export function listCommands() {
  return [...COMMANDS].sort((a, b) => a.name.localeCompare(b.name));
}

export function commandGroups() {
  const groups = new Map();
  for (const command of listCommands()) {
    if (!groups.has(command.group)) groups.set(command.group, []);
    groups.get(command.group).push(command);
  }
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
}
