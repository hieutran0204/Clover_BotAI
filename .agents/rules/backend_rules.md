# Backend Agent Rules

These rules load every session. Fill in the `[FILL IN]` items once per project, then delete this line.

## Project
- Stack: [FILL IN: e.g. Node.js + NestJS + PostgreSQL]
- Install / dev / test / lint / build commands: [FILL IN]
- Spec: `SPEC.md` (created by `/spec`). Plan: `PLAN.md` (created by `/plan`).

## Workflow (do not skip steps)
1. `/spec` → write `SPEC.md`. The user approves it.
2. `/plan` → write `PLAN.md`: small tasks, each with acceptance criteria. The user approves it.
3. `/build` → implement ONE task, then stop. Never use `/build auto` unless the user asks for it.
4. `/test` → `/review` → commit once the task's acceptance criteria are met.
5. `/ship` only when the user asks.

No code before an approved spec and plan, except a trivial fix the user asked for directly.

## Scope rules (hard rules)
- Do only the current task in `PLAN.md`. Nothing more.
- Do not touch files outside the task. No refactors, renames, dependency upgrades, or "while I'm here" cleanups.
- If you notice something worth fixing outside the task, list it under `NOTICED BUT NOT TOUCHING` and carry on. Do not fix it.
- If the task needs more than planned (new endpoint, changed requirement, new dependency, new table or column), STOP. Say what and why, then ask. Update `SPEC.md` / `PLAN.md` only after the user agrees.
- Never lower the quality bar to make a task pass: no deleted or skipped tests, no lint suppressions, no loosened thresholds.
- One logical change per commit.
- Request unclear? Ask one question. Do not guess the scope.

## Done means
The task meets its acceptance criteria and `.claude/references/definition-of-done.md`.

## Backend-specific
- API work follows `api-and-interface-design`. A change to an existing endpoint, response shape, or error format is a breaking change: ask first.
- Database schema changes and migrations need explicit approval. Use expand/contract (`deprecation-and-migration`); never drop or rename in one step.
- Security: `security-and-hardening`, `.claude/references/security-checklist.md`. Never log secrets or tokens, never build SQL from strings.
- Logs, metrics, alerts: `observability-and-instrumentation`, `.claude/references/observability-checklist.md`.
- Performance: measure first with `EXPLAIN ANALYZE` / profiling (`performance-optimization`). No index or cache without a measurement.
- Auth, payments, data deletion, or any irreversible operation: use `doubt-driven-development` before proceeding.
