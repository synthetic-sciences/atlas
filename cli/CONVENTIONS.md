# Atlas CLI naming conventions

The registry in `src/atlas-runtime/commands.mjs` is the single source of
truth for command names. `cli/tests/conventions.test.mjs` enforces the rules
below — a new command that violates them fails CI.

## Command shape

```
atlas <namespace>:<verb> [--flags]
atlas <namespace>:<sub>:<verb>      # at most three levels
atlas <bare-verb>                   # session-level commands only
```

## Rules

1. **Namespaces are singular nouns.** `node:`, `label:`, `key:`, `secret:`,
   `integration:`, `project:`, `run:`, `eval:`, `hypothesis:`,
   `experiment:`, `decision:`, `optimize:` — matching the namespaces that
   were always singular (`map:`, `link:`, `draft:`, `evidence:`, `config:`).
   Plural forms of pre-0.8 names remain as hidden
   aliases while the underlying product remains supported. (`optimize:` is a
   verb-noun whose resource is the optimization run.)

2. **One verb vocabulary.** Prefer, in order of specificity:
   - `list / show / create / update / delete` for plain CRUD on a resource.
   - `add` when attaching something to an existing parent (`evidence:add`,
     `note:add`, `link:add`, `hypothesis:add` — all create a child of
     something you point at).
   - `set / unset / clear` for configuration-like state.
   - Domain verbs (`record`, `compare`, `plan`, `define`, `sync`, `grep`,
     `ask`, `search`, `pin`, `capture`, `push`, `merge`, `share`, `scope`)
     only when the action genuinely isn't CRUD.

3. **Bare commands are reserved** for session-level actions an agent or
   human runs without thinking about a resource: `login`, `logout`,
   `whoami`, `doctor`, `install`, `brief`, `leaderboard`, `reproduce`.
   Everything else must be namespaced. The whitelist lives in the
   conventions test; extending it is a deliberate review decision.

4. **The word "run" means an experiment run** (Flight Recorder). Never
   reintroduce a second meaning of "run".

5. **Targets use two canonical flags**: `--project <slug|id>` and
   `--node <slug|id>` (slug-resolved automatically). Longer spellings
   (`--project-id`, `--node-id`, `--root-node-id`) stay accepted, but docs,
   skills, and help text always show the short canonical form.

6. **Renames keep aliases while the product exists.** A product surface that
   is deliberately decommissioned is removed rather than kept as a hidden
   executable alias.

7. **Destructive commands** require `--yes` and are marked
   `destructive: true` in the registry — no exceptions.

8. **HTTP paths are not names.** Backend route paths (`/runs:record`,
   `/nodes/{id}`) are wire compatibility surface and do not need to track
   CLI renames.

## Pre-0.8 → 0.8 rename table

| old (still works) | canonical |
|---|---|
| `nodes:*` | `node:*` |
| `labels:*` | `label:*` |
| `keys:*` | `key:*` |
| `secrets:*` | `secret:*` |
| `integrations:*` | `integration:*` |
| `projects:merge` | `project:merge` |
| `runs:record/compare` | `run:record/compare` |
| `runs:spool:*` | `run:spool:*` |
| `github:refresh` | `github:reconnect` |
