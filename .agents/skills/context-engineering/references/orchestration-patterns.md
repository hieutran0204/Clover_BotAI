# Orchestration Patterns

Reference catalog of agent orchestration patterns this repo endorses, plus anti-patterns to avoid. Read this before adding a new workflow that coordinates multiple review passes, or before introducing a new persona-style interaction.

The governing rule: **the user (or a slash command) is the orchestrator. Skills do not invoke other skills without user direction.**

---

## Endorsed Patterns

### 1. Direct invocation (no orchestration)

Single skill, single perspective, single artifact. The default and the cheapest option.

**Use when:** the work is one perspective on one artifact and you can describe it in one sentence.

**Examples:**
- "Review this PR" → `code-review-and-quality` skill
- "Find security issues in `auth.py`" → `security-and-hardening` skill
- "What tests are missing for the checkout flow?" → `test-driven-development` skill

---

### 2. Sequential pipeline (user-driven)

The user runs commands in a defined order, carrying context between them. There is no orchestrator — the user IS the orchestrator.

```
user runs:  /spec  →  /plan  →  /build  →  /test  →  /review  →  /ship
```

**Use when:** the workflow has dependencies and human judgment between steps adds value.

**Why not automate it:** an LLM lifecycle orchestrator would lose nuance between steps, skip human checkpoints, and double token cost via paraphrasing turns.

---

### 3. Parallel review with merge (/ship)

Multiple review perspectives run against the same input, each producing an independent report. A merge step synthesizes them into a single go/no-go decision.

```
/ship → code review + security audit + coverage analysis → merge → go/no-go + rollback
```

**Use when:**
- The sub-tasks are genuinely independent
- The merge step is small enough to stay in the main context
- Wall-clock latency matters

---

### 4. Research isolation (context preservation)

When a task requires reading large amounts of material that shouldn't pollute the main context.

**Use when:**
- The main session needs to stay focused on a downstream task
- The investigation result is much smaller than the input it consumes

**Examples:** "Find every call site of this deprecated API across the codebase," "Summarize what these ADRs say about caching."

---

## Anti-Patterns

### A. Router "meta-orchestrator"

A skill whose job is to decide which other skill to call.

**Why it fails:** pure routing layer with no domain value, adds paraphrasing hops → information loss.

**Instead:** add or refine workflow commands.

---

### B. Skill that calls another skill

**Why it fails:** chaining skills defeats single-perspective design; failure modes multiply.

**Instead:** have the skill *recommend* a follow-up. The user or a command runs the second pass.

---

### C. Sequential orchestrator that paraphrases

An agent that runs /spec, then /plan, then /build automatically without human checkpoints.

**Why it fails:** loses the human checkpoints, accumulated context drift over a long pipeline, removes user agency.

**Instead:** keep the user as the orchestrator. Document the recommended sequence and let users invoke it.

---

## Decision Flow

```
Is the work one perspective on one artifact?
├── Yes → Direct invocation. Stop.
└── No  → Will the same composition repeat?
         ├── No  → Direct invocation, ad hoc. Stop.
         └── Yes → Are sub-tasks independent?
                  ├── No  → Sequential commands run by user.
                  └── Yes → Parallel review with merge.
```
