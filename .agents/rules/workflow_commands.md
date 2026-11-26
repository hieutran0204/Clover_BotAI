# Workflow Commands

These define the behavior for each workflow command. When the user says "run spec", "run plan", "build", "test", "review", "ship", "code-simplify", or "constraints", follow the corresponding procedure below.

---

## /spec — Spec-Driven Development

Invoke the `spec-driven-development` skill.

Begin by understanding what the user wants to build. Ask clarifying questions about:
1. The objective and target users
2. Core features and acceptance criteria
3. Tech stack preferences and constraints
4. Known boundaries (what to always do, ask first about, and never do)

Then generate a structured spec covering all six core areas: objective, commands, project structure, code style, testing strategy, and boundaries.

If the request bundles several independently testable capabilities, first propose a capability map (module ids, dependency direction, build order) and get it approved, then spec each module in dependency order.

Save the spec as SPEC.md in the project root and confirm with the user before proceeding.

---

## /plan — Planning and Task Breakdown

Invoke the `planning-and-task-breakdown` skill.

Read the existing spec (SPEC.md or equivalent) and the relevant codebase sections. Then:

1. Enter plan mode — read only, no code changes
2. Identify the dependency graph between components
3. Slice work vertically (one complete path per task, not horizontal layers)
4. Write tasks with acceptance criteria and verification steps
5. Add checkpoints between phases
6. Present the plan for human review

Save the plan to tasks/plan.md and task list to tasks/todo.md.

If tasks/plan.md or tasks/todo.md already exists with unchecked tasks for different work, stop and ask before writing — never silently overwrite an incomplete plan.

---

## /build — Incremental Implementation

Invoke the `incremental-implementation` skill alongside `test-driven-development`.

### Default: one task

Pick the next pending task from the plan. Then:

1. Read the task's acceptance criteria
2. Load relevant context (existing code, patterns, types)
3. Write a failing test for the expected behavior (RED)
4. Implement the minimum code to pass the test (GREEN)
5. Run the full test suite to check for regressions
6. Run the build to verify compilation
7. Commit with a descriptive message
8. Mark the task complete and stop

### /build auto — Autonomous mode

1. **Require a spec.** Look for SPEC.md at the repo root, `docs/SPEC.md`, or `spec/`. If none exists, stop and tell the user to run `/spec` first.
2. **Establish a clean baseline.** Run `git status --porcelain`. If uncommitted changes exist outside planning artifacts, stop and ask.
3. **Plan if needed.** If there is no `tasks/plan.md`, invoke `planning-and-task-breakdown` to generate one.
4. **Single checkpoint.** Present the full plan and wait for an unambiguous affirmative. This is the only human gate.
5. **Execute every task in dependency order.** For each task: RED → GREEN → regression → build → commit → mark complete.
6. **Stop and ask** when a test can't pass, spec is ambiguous, or a task is high-risk (auth, payments, data deletion, irreversible ops).
7. **Summarize at the end:** tasks completed, tests added, commits made, anything skipped or flagged.

---

## /test — TDD Workflow

Invoke the `test-driven-development` skill.

For new features:
1. Write tests that describe the expected behavior (they should FAIL)
2. Implement the code to make them pass
3. Refactor while keeping tests green

For bug fixes (Prove-It pattern):
1. Write a test that reproduces the bug (must FAIL)
2. Confirm the test fails
3. Implement the fix
4. Confirm the test passes
5. Run the full test suite for regressions

---

## /review — Five-Axis Code Review

Invoke the `code-review-and-quality` skill.

Review the current changes across all five axes:

1. **Correctness** — Does it match the spec? Edge cases handled? Tests adequate?
2. **Readability** — Clear names? Straightforward logic? Well-organized?
3. **Architecture** — Follows existing patterns? Clean boundaries? Right abstraction level?
4. **Security** — Input validated? Secrets safe? Auth checked? (Use `security-and-hardening` skill)
5. **Performance** — No N+1 queries? No unbounded ops? (Use `performance-optimization` skill)

Categorize findings as Critical, Required, Optional, or Nit.
Output a structured review with specific file:line references and fix recommendations.

---

## /ship — Pre-Launch Fan-Out Review

Invoke the `shipping-and-launch` skill.

### Phase A — Parallel review (all three perspectives)

1. **Code review** — Five-axis review (correctness, readability, architecture, security, performance)
2. **Security audit** — OWASP Top 10, secrets, auth/authz, dependency CVEs
3. **Test coverage** — Coverage gap analysis for happy path, edge cases, error paths, concurrency

### Phase B — Merge and synthesize

Aggregate findings from all three passes. Resolve duplicates. Cross-check Critical findings.

### Phase C — Decision output

```markdown
## Ship Decision: GO | NO-GO

### Blockers (must fix before ship)
### Recommended fixes (should fix before ship)
### Acknowledged risks (shipping anyway)
### Rollback plan
- Trigger conditions:
- Rollback procedure:
- Recovery time objective:
```

**Rules:**
- Critical finding → default NO-GO unless user explicitly accepts the risk.
- Skip full review only if: ≤2 files, diff <50 lines, AND does not touch auth/payments/data/config.

---

## /code-simplify — Code Simplification

Invoke the `code-simplification` skill.

Simplify recently changed code while preserving exact behavior:

1. Read project conventions and study the target code
2. Understand purpose, callers, edge cases, and test coverage before touching it
3. Scan for opportunities: deep nesting, long functions, nested ternaries, generic names, duplicated logic, dead code
4. Apply each simplification incrementally — run tests after each change
5. Verify all tests pass, the build succeeds, and the diff is clean

If tests fail after a simplification, revert that change and reconsider.

---

## /constraints — Constraint-Driven Development

Invoke the `constraint-driven-development` skill.

1. **Detect first.** Read pyproject.toml / requirements.txt, test runner, lint configs, coverage output, CI workflows. Never ask for anything you can read.
2. **Interview, at most four questions.** One at a time with defaults: which dimensions, block or warn, target numbers, slowest tolerable check.
3. **Write CONSTRAINTS.md** at the repo root with a Floor section, enforced numbers, measured metrics, and exceptions table.
4. **Install what each dimension needs.** Record exact commands in CONSTRAINTS.md.
5. **Place each check by cost.** Types/lint/secrets in edit loop. Tests at task end. Everything else at review/CI.

Sub-commands:
- `/constraints check` — run the current constraints against this branch
- `/constraints guard` — inspect the diff for a weakened bar
- `/constraints ratchet` — record today's measured values as the floor
