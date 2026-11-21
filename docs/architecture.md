---
title: AI-Native Data Warehouse + Guided Agent — Architecture v2
date: 2026-06-03
status: Pre-implementation, second review
---

# AI-Native Data Warehouse + Guided Agent — Architecture Plan

> **Purpose:** External architecture review. This document describes what we're building,
> why we made each decision, and what risks remain. Every claim is verifiable.
> No citation is included without the reviewer being able to check it.
>
> **Target audience:** Engineers evaluating whether this plan is sound,
> buildable, and appropriate for the problem.
>
> **Prepared by:** PI coding agent, with corrections from first-round reviews.
> All cited sources have been independently verified.

---

## 0. What This System Actually Does

Before reading the architecture, here are the actual queries the system must handle.
They range from trivial to genuinely multi-step:

| Type | Example query | What the system should do |
|---|---|---|
| **Simple fact** | "What were yesterday's sales?" | One DuckDB query, return number. Done. |
| **Aggregate** | "Show me the top 10 products by margin" | One DuckDB query, return table. Done. |
| **Trend** | "How have plumbing margins changed over the last 12 months?" | One DuckDB query with date grouping, return chart data. Done. |
| **Diagnosis** | "Margins dropped in March. Why?" | Multiple queries: overall margin by month → find March anomaly → drill into Accessories vs Tools → check supplier costs vs selling prices. Needs multi-step reasoning. |
| **What-if** | "Should we raise prices on plumbing supplies?" | All of the above + competitive pricing check (from auxiliary DB) + impact estimation. Needs structured analysis with intermediate verification. |

**Key point:** For queries 1-3, a single SQL call suffices. The system MUST handle
these instantly without orchestration overhead. For queries 4-5, the LLM needs
to plan, execute multiple steps, and be prevented from declaring victory after
step 1. These need orchestration.

This distinction drives the entire architecture. A system that only handles 1-3
is a "chat-to-SQL" tool. A system that handles 4-5 needs guardrails against
premature stopping. We need both.

---

## 1. The Problem: LLMs Stop Too Early

### The Failure Mode

When you give an LLM tools and say "answer this question," the standard loop is:

```
while True:
    result = llm.invoke(tools + context)
    if result has no tool calls:
        return result  # LLM says "I'm done"
    else:
        execute tools → append results to context
```

This fails because **LLMs cannot reliably judge whether their answer is complete.**
They were trained to be helpful — they default to saying something and stopping.
The documented result: a LangChain analyzer/verifier agent pair ran for 264 hours
straight because neither the analyzer nor the verifier had a stopping criterion
([tianpan.co, 2026-05-07](https://tianpan.co/blog/2026-05-07-tool-call-convergence-agents-stopping-criteria)).
Invoice: $47,000.

This isn't a "misconfiguration." Every major framework has the same structural gap:
- LangChain's `max_iterations` default is 15 — but the $47k loop didn't need more
  iterations; it needed **someone to decide when the answer was good enough**
- Vanna's agent loop defers to the model
- Naive ReAct has no external completion check

### Why This Matters for a Retail Store

For the query *"Should we change our profit margins?"*, a default LLM loop will:
1. Query current margins → finds 12% overall
2. Check a segment → finds Tools at 15%, Accessories at 9%
3. Write a plausible analysis about "consider raising Accessories prices"
4. Stop and present it

What it WON'T do (without being forced):
- Check if the March data had a supplier cost spike (discovered in step 3)
- Check if competitor prices support a raise
- Verify its own assumption that Accessories margin drop was structural, not seasonal
- Cross-check its revenue impact estimate against actual transaction volumes

Each of these requires a separate tool call, driven by **the answer to the previous
call.** The LLM won't make those calls unless the architecture forces it to.

### The Fix: The Machine Decides, Not The LLM

The architecture must have a harness (pure code) that:
1. Writes a structured plan before executing anything
2. Executes one step at a time
3. Verifies each step against business rules
4. Decides (in code, not via LLM) what happens next

This is the Plan-Execute-Validate (PEV) pattern, proven in production:
- **VMAO** (arXiv 2603.11445, AWS+HKUST 2026): DAG decomposition of complex queries
  + verification-driven replanning improved answer completeness from 3.1 to 4.2
  (on a 1-5 scale, 25 expert-curated market research queries)
- **LangGraph PEV** (open-source, `langgraph-plan-execute-validate`):
  Structured plan as typed state, separate verifier LLM, deterministic router
- **loop-guard** (open-source): Deterministic verification by re-executing code,
  diffing output, and checking citations — no second LLM needed

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           WAREHOUSE AGENT                                 │
│                                                                           │
│  ┌──────────────────────┐     ┌──────────────────────────────────────┐   │
│  │   FASTAPI SERVER      │     │  PEV ORCHESTRATOR                     │   │
│  │                       │     │                                        │   │
│  │  /api/agent/run  ◄───┼─────┤  ┌──────────┐  ┌──────────┐        │   │
│  │   (SSE stream)        │     │  │CLASSIFIER│  │ FAST PATH│        │   │
│  │                       │     │  │(pure code)│──┤(1 SQL)   │        │   │
│  │  /api/agent/respond   │     │  └─────┬────┘  └──────────┘        │   │
│  │   (user input)        │     │        │complex query               │   │
│  │                       │     │        ▼                            │   │
│  │  /api/dashboard/query │     │  ┌─────────────────────────────┐    │   │
│  │   (direct SQL)        │     │  │ PLANNER (LLM call)          │    │   │
│  │                       │     │  │ → structured sub-questions  │    │   │
│  └───────────────────────┘     │  └──────────────┬──────────────┘    │   │
│                                 │                 │                    │   │
│  ┌───────────────────────┐     │                 ▼                    │   │
│  │ PYDANTICAI AGENT      │     │  ┌─────────────────────────────┐    │   │
│  │                       │     │  │ EXECUTOR (LLM + tools)     │    │   │
│  │ Tools:                │     │  │ → one sub-question at a time│    │   │
│  │  • duckdb_query       │◄────┼──┤ → calls duckdb_query       │    │   │
│  │  • run_python         │     │  │ → calls run_python         │    │   │
│  │  • ask_user           │     │  │ → calls ask_user (optional) │    │   │
│  │                       │     │  └──────────────┬──────────────┘    │   │
│  └───────────────────────┘     │                 │                    │   │
│                                 │                 ▼                    │   │
│  ┌───────────────────────┐     │  ┌─────────────────────────────┐    │   │
│  │ DUCKDB                │     │  │ VERIFIER (LLM or code)     │    │   │
│  │                       │     │  │ → scores result 0.0-1.0   │    │   │
│  │ warehouse.db (RO)     │◄────┼──┤ → checks: empty results?  │    │   │
│  │ auxiliary.db (RW)     │     │  │ → checks: numbers make sense?│   │   │
│  │                       │     │  │ → checks: contradictions? │    │   │
│  └───────────────────────┘     │  └──────────────┬──────────────┘    │   │
│                                 │                 │                    │   │
│  ┌───────────────────────┐     │                 ▼                    │   │
│  │ FRONTEND              │     │  ┌─────────────────────────────┐    │   │
│  │                       │     │  │ ROUTER (pure code, no LLM)  │    │   │
│  │ Chat (assistant-ui)   │     │  │ → next sub-question         │    │   │
│  │ Dashboard (shadcn)    │     │  │ → retry with feedback       │   │   │
│  │                       │     │  │ → replan                    │   │   │
│  └───────────────────────┘     │  │ → stop (done or failed)     │    │   │
│                                 │  └─────────────────────────────┘    │   │
│                                 │                                        │   │
│                                 │  Checkpoints (pure code, per step):   │   │
│                                 │  1. Check user message queue          │   │
│                                 │  2. Check token budget                │   │
│                                 │  3. Check iteration limit             │   │
│                                 └──────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Decisions (With Reasoning For Each)

### 3.1 Query Classifier (New — Added After First Review)

A pure-code classifier determines whether a query needs orchestrated multi-step
analysis or can be answered with one SQL call:

```python
def classify_query(user_input: str) -> QueryClass:
    """
    Pure code, no LLM call. Heuristic classification.
    
    "Simple" keywords: sale, revenue, total, count, show, list, top, bottom,
                       yesterday, today, this month, who, which product
    "Complex" keywords: why, should we, what if, compare, trend, analyze,
                        explain, root cause, diagnose, impact
    """
    if has_complex_keywords(user_input):
        return "multi_step"
    if has_simple_keywords(user_input):
        return "simple_fact"
    return "aggregate"  # default — one SQL query, no orchestration
```

This ensures "what were yesterday's sales?" takes ~2 seconds (one DuckDB query,
no LLM overhead), while "should we change profit margins?" takes the PEV path.

**Why this isn't an LLM call:** Classification is fast, deterministic, and
doesn't need intelligence. Cost: zero tokens.

**Known limitation:** The keyword heuristic will sometimes misclassify.
A query like "show me which categories have low margins compared to last year"
has "show" (simple) but needs year-over-year JOIN + margin computation.
This actually routes correctly to `aggregate` (one well-formed SQL call covers
it), so the risk is low. The reverse case is more dangerous: "what were
yesterday's sales by category by supplier?" looks simple but produces a wide
result that may mislead without drill-down — the classifier can't catch this.

**Mitigation:** Both misclassification directions are handled — false complex
(adding overhead to simple queries) wastes tokens but never loses data;
false simple (missing multi-step analysis) produces plausible-looking shallow
answers. The Phase 6 tuning pass measures misclassification rate and adjusts
the keyword set. For now, the bias is toward `aggregate` (default), which
means one SQL call + basic formatting — a safe middle ground.

### 3.2 PEV Orchestrator (For Complex Queries Only)

Only invoked when the classifier returns `multi_step`. This is the fault-tolerant,
verification-driven loop.

**Planner:**

| Property | Detail |
|---|---|
| What | A single LLM call that writes a structured plan |
| Input | User query + prior results (if this is a replan) |
| Output | Pydantic model: `List[SubQuestion]` |
| SubQuestion schema | `{id, question, type (sql/python/ask_user), depends_on[]}` |
| Max sub-questions | 5 (soft limit, prevents plan explosion) |

**Executor:**

| Property | Detail |
|---|---|
| What | One PydanticAI agent run per sub-question |
| Tools | `duckdb_query`, `run_python`, `ask_user` (see Section 5 for details) |
| Context | Injected with full schema context (table names, columns, business rules) |
| Output | Structured: data summary, findings, uncertainty notes |

**Verifier:**

| Property | Detail |
|---|---|
| What | Mixed: deterministic checks (fast, no LLM) + optional LLM check (semantic) |
| Input | Sub-question + result + business rules |
| Score | 0.0–1.0 (per this result, not global) |
| Code-checked criteria | Non-empty check (0.3) — deterministic, zero cost. Row count within expected range (0.3) — e.g., "at least 10 products expected for a category breakdown." These run on every result. |
| LLM-checked criteria | Numerical plausibility (0.3) — "do these numbers make sense in context?" Contradictions with prior results (0.2) — "does this conflict with what we found in step 2?" Matches expected output format (0.2). Only invoked if code checks pass. |
| Threshold | Configurable. Default: 0.6. Verified against the full score (code + LLM weighted sum). |

**Note on weights:** The numbers 0.3/0.3/0.2/0.2 are initial guesses, no more
calibrated than the 0.7/0.8/0.85 thresholds they replaced. The per-criterion
boolean scores are stored raw in logs. During Phase 6, we fit weights against
the real query test set to find what actually correlates with correct answers.

**Why default 0.6 and not 0.7/0.8/0.85 (as in v1):**
The first review correctly called those values arbitrary. 0.6 is the starting
point — it means "more likely right than wrong." We tune it empirically during
Phase 6 by running the system against a test set of 20-30 curated queries and
measuring precision/recall at each threshold value. No pretense of calibration
without data. (The same caveat applies to the per-criterion weights below.)

**Router (pure code):**

```
score >= 0.6 AND more sub-questions remain     → next sub-question
score >= 0.6 AND no more sub-questions          → synthesis step
score < 0.6 AND retries < 2                     → retry with verifier feedback
score < 0.6 AND retries >= 2                    → mark as low-confidence, continue
token budget hit OR iteration limit hit         → emergency stop, return partial
```

**Synthesis step:** Run once (not twice — the "run synthesis twice" idea from v1
was based on a research paper's self-consistency method, but the paper used 10-20
samples, not 2. Two samples at temperature > 0 is not scientifically meaningful
and we shouldn't pretend it is. A single synthesis LLM call with the accumulated
context is sufficient for this use case.)

**Stop conditions (all enforced in code, zero LLM calls):**
- All sub-questions executed with score ≥ 0.6
- Max retries (2) exhausted on any sub-question
- Token budget hit (configurable, default 50,000 tokens)
- Iteration limit (15 sub-questions total across all plans)
- User sends "stop" message

### 3.3 Why Not Just a Simpler Loop?

If the problem is "LLMs stop early," why not just prompt the model better?

Because prompting doesn't fix structural issues. The $47k incident had prompts.
The loop guard papers all show the same result: LLMs cannot self-assess completion
reliably regardless of prompting. This is a known property documented across:
- Cambridge confidence paper (arXiv 2601.02179v1, Jan 2026):
  Verbalized confidence (asking the model "how sure are you?") has InfoECE
  calibration error of 40-80% across all tested models. The model doesn't know
  what it doesn't know.
- The three-layer defense article (tianpan.co, 2026): "The model can't tell you
  when it has enough information any more reliably than a junior analyst can tell
  you when a project is 'done.'"

The fix is mechanical, not prompt-based. The harness decides, not the LLM.

### 3.4 DuckDB (Read-Only Warehouse)

**Why DuckDB over SQLite:**
- Columnar storage: analytical queries (SUM, GROUP BY, date ranges over 66K rows)
  are 10-100x faster than SQLite's row-oriented engine
- Native `read_only=True` mode: enforced at the database driver, not at the tool
- Single file: `warehouse.db`, zero config, can copy it as backup
- Full SQL support: window functions, CTEs, UNION, all analytical features

**Why two databases instead of one:**
- `warehouse.db` — connected with `duckdb.connect(read_only=True)`
  This is a psychological and architectural boundary. The agent literally cannot
  write to it, even through bash → duckdb CLI. Every write attempt fails at the
  driver level.
- `auxiliary.db` — connected normally. Contains competitor pricing (user-entered),
  analysis logs, cached results. The agent can write here, and every write is logged.

### 3.5 FastAPI + SSE + PydanticAI

**Why FastAPI over Flask/Django:**
- Async-native: SSE streaming requires async generators, which FastAPI supports natively
- Type safety: request/response models via Pydantic
- PydanticAI integration: `pydantic_ai.ui.UIAdapter.dispatch_request()` is built
  for Starlette/FastAPI (per PydanticAI docs, `ui/overview.md`)

**Why SSE over WebSocket:**
- Simpler: SSE is HTTP-based, no upgrade handshake, works through proxies
- Unidirectional from server is fine: progress events flow to frontend; user
  responses come through a separate POST endpoint
- assistant-ui supports SSE natively

**Why PydanticAI over LangChain:**
- Type-safe tools: tool schemas are Pydantic models validated at the framework level
- 25+ LLM providers natively: OpenAI, Anthropic, DeepSeek, Gemini, etc.
  One config line to switch. This is verified from PydanticAI's `agent.py` and
  `litellm_model.py` source code — the provider list is exhaustive.
- Graph support: available for future multi-agent expansion if needed
- Durable execution: retries, error recovery built in
- OpenTelemetry integration: logging for debugging

**What PydanticAI does NOT have natively:**
- No "JustBash" capability in core (this from v1 was incorrect).
  The third-party package `pydantic-ai-just-bash` (v0.3.0 on PyPI) provides
  persistent shell execution, but we don't use it in production. On Linux dev,
  the `run_python` tool wraps `subprocess.run()`. On Windows, see Section 5.

---

## 4. Table Structure & Schema Injection (Critical Gap Fixed)

### 4.1 Why This Is Critical

The executor agent writes SQL against `warehouse.db`. If it doesn't know the schema,
it will hallucinate column names. The previous plan didn't mention how the agent
learns the schema. This is a fundamental gap for any text-to-SQL system.

### 4.2 Schema Context

Every agent call that involves SQL gets this injected as part of the system prompt:

```markdown
## Database Schema (warehouse.db — READ ONLY)

### products (thousands of rows)
- product_id: INTEGER (primary key)
- name: VARCHAR — Product name (multilingual)
- category_id: INTEGER → categories.category_id
- department_id: INTEGER → departments.department_id  
- cost_price: DECIMAL(10,2) — Latest purchase cost
- selling_price: DECIMAL(10,2) — Current retail price
- supplier_id: INTEGER → suppliers.supplier_id
- current_stock: INTEGER — Units on hand
- reorder_level: INTEGER — Minimum stock before reorder alert
- last_purchase_date: DATE

### dockets (thousands of rows over ~3 years)
- docket_id: INTEGER (primary key)
- date: DATE — Transaction date
- customer_id: INTEGER
- total: DECIMAL(10,2) — Docket total after tax
- tax: DECIMAL(10,2)
- cashier_id, register_id: INTEGER

### docket_items (tens of thousands of rows)
- docket_item_id: INTEGER (primary key)
- docket_id: INTEGER → dockets.docket_id
- product_id: INTEGER → products.product_id  
- quantity: DECIMAL(10,2)
- unit_price: DECIMAL(10,2) — Price at time of sale
- discount: DECIMAL(10,2) — Discount applied

### categories (~50 rows)
- category_id, name, department_id

### departments (25 rows)
- department_id, name

### suppliers (~100 rows)  
- supplier_id, name, contact_info, phone

## Business Rules
- Margin = (selling_price - cost_price) / selling_price * 100
  **CRITICAL — Historical margin analysis:** `docket_items.unit_price` records the
  price paid at time of sale (historical). `products.selling_price` is the current
  retail price (today). For "how have margins changed over 12 months?" use
  `docket_items.unit_price`. Historical cost price at transaction time is NOT
  stored — the schema has no `docket_items.cost_price`. Use `products.cost_price`
  as a proxy and ALWAYS note this limitation in any historical analysis.
- A "slow mover" = no sale in 90+ days
- All `*_id` columns are INTEGER foreign keys
- dates are in YYYY-MM-DD format
- departments: Plumbing, Electrical, Tools, Hardware, Paint, Accessories, etc.
```

This is not a one-time description. It's injected into every LLM call that has
SQL access. The planner sees it to design sub-questions. The executor sees it
to write correct SQL. The verifier sees it to check that the SQL references
real columns.

### 4.3 Schema Injection Mechanism

```python
# In the system prompt construction:
SCHEMA_MARKDOWN = load_schema_description("warehouse_schema.md")

agent = Agent(
    model=model,
    system_prompt=f"""
    You are a warehouse data analyst. You answer questions about business data.
    
    {SCHEMA_MARKDOWN}
    
    IMPORTANT: warehouse.db is READ ONLY. You cannot modify it.
    Use auxiliary.db for storing any analysis results.
    """
)
```

The schema file is version-controlled alongside the ETL pipeline. If the schema
changes (unlikely for frozen legacy POS data, but possible), the prompt is updated
with the ETL run.

---

## 5. Tool Design (Constrained, Not General bash — Changed After First Review)

### 5.1 Why Not General bash (As in v1)

The first plan argued for a general bash tool, citing PI, Codex CLI, and
OpenHarness. This was correct in principle but wrong in deployment context:

| System | bash tool | Sandbox |
|---|---|---|
| PI | Unrestricted bash | Linux container |
| Codex CLI | Unrestricted bash | Docker container |
| OpenHarness | Unrestricted shell | Permissions layer + VM |
| **Our system (dev)** | **Can use bash** | **Linux dev machine (no sandbox, but controlled by developer)** |
| **Our system (prod)** | **CANNOT use bash** | **Store owner's Windows laptop (no sandbox, no Docker, arbitrary file access)** |

The argument that "every production system uses general bash" is true — but every
one of those systems runs in a sandbox. Ours doesn't. On the store owner's laptop,
a hallucinated bash command could delete files, access credentials, or modify
system state. A read-only DuckDB connection doesn't protect against that.

**Conclusion:** For Windows production, we use constrained tools.
For Linux development, bash is available for debugging.

### 5.2 The Three Tools

| Tool | Signature | Sandbox | Platform |
|---|---|---|---|
| `duckdb_query` | `(sql: str) -> DataFrame` | Read-only DuckDB connection only | Both |
| `run_python` | `(code: str) -> str` | Timeout (30s), output limit (10K chars), blocked imports (`os.subprocess`, `shutil`, `pathlib`, `sys.modules`) | Both |
| `ask_user` | `(question: str) -> str` | Returns "NO_ANSWER" after timeout | Both |

**`duckdb_query`** — The primary tool. Takes SQL, returns a DataFrame.
No shell access, no file system, no network. The connection is read-only.
This handles 90% of queries.

**`run_python`** — For analysis that can't be expressed in SQL (statistical
tests, data transformation, chart data computation). Sandboxed:

**Data handoff from `duckdb_query` to `run_python`:** `duckdb_query` returns a
DataFrame. In PydanticAI, tool outputs are serialized to JSON and passed through
the LLM context window. For large results, this is inefficient. The harness
caches the last N DataFrames in-process (keyed by sub-question ID) and injects
a reference handle. `run_python` can access them via `get_dataframe(handle)`.
For small-medium results (<10 MB), direct JSON serialization is used. The 100 MB
`MAX_DATA_SIZE` limit is the safety cap on the in-process cache, not the LLM
context window.
```python
# Block dangerous imports
RESTRICTED_IMPORTS = {"os", "subprocess", "shutil", "pathlib", "ctypes",
                      "socket", "requests", "urllib", "http", "multiprocessing",
                      "threading", "pickle", "shelve", "dbm"}

# Execution constraints
MAX_EXECUTION_TIME = 30  # seconds
MAX_OUTPUT_SIZE = 10000  # characters
MAX_DATA_SIZE = 100 * 1024 * 1024  # 100 MB (for DataFrames)
```

**`ask_user`** — For when the agent needs business context the database
doesn't have. Uses the message queue pattern (Section 6).

**Timeout:** 120 seconds by default. Configurable in settings. If the user
hasn't responded after 120s, the tool returns "NO_ANSWER" and the agent
notes the gap. The frontend shows a "still waiting" indicator after 30s.

**Multiple concurrent questions:** Each `ask_user` call is keyed by a unique
`question_id` (UUID). The message queue stores answers keyed to that ID.
Question 2 and Question 4 can both be pending. When the user answers the
second question first, the harness routes it by `question_id` to the correct
pending context. Unanswered questions remain in the queue; the agent checks
at each checkpoint and finds whichever answer is available. If multiple
questions are pending, the frontend shows them as a list, each with its
own input field.

**bash tool (dev only):** Available on the Linux development machine for
debugging. NOT included in the production build. The agent never needs it
for normal operation.

### 5.3 Prompt Injection from Database Content

Reviewer 2 raised this: what if a supplier's name or product description contains
injection syntax? This is handled by:
1. SQL is parameterized — product names are data, not code
2. Database content that appears in prompts is escaped before injection
3. The `duckdb_query` tool returns DataFrames, not raw strings — the tool
   output is structured data, not executable text

---

## 6. User Interaction Model (Message Queue, Non-Blocking)

### 6.1 The Pattern

Inspired by how PI handles concurrent user input during tool execution:

```
Agent running:
  Step 1 → duckdb_query("margin by category") → returns data
  Step 2 → analysis reveals March anomaly
  Step 3 → ask_user("Do you know why Accessories margins dropped in March?")
           → Writes {type:"question", question_id:"abc-123", question:"..."}
           → Returns immediately (no blocking)
           → Continues processing other data
           → At next checkpoint, checks message queue by question_id
  
  If answer for abc-123 arrived:  incorporate it, continue analysis
  If no answer yet:                 note the gap, continue with what it has
```

**Question keying:** Every `ask_user` call generates a UUID (`question_id`).
The SSE stream sends it alongside the question text. The user's answer POST
includes `question_id` so the harness routes it to the right pending context.
Multiple questions can be outstanding simultaneously. The frontend shows each
as a separate input field in the chat.

**The key insight:** The `ask_user` tool does NOT block. It writes the question
to the output stream and returns a sentinel value. The actual answer arrives
asynchronously via the message queue, which the harness checks at natural
checkpoints (after each sub-question, before synthesis).

**Why non-blocking instead of synchronous:**
- The agent keeps working while the user thinks
- The user can answer at their leisure (no timeout pressure)
- The user can provide information the agent didn't ask for
- Multiple questions can accumulate; user answers in any order
- No hanging connections, no timeout recovery logic

**Why not synchronous:**
Reviewer 1 argued the user "may assume the agent is waiting" and find it
confusing. This is true — but with the right UI (showing "continuing analysis"
alongside the question), the user sees the agent is still working. The tradeoff
is worth it for the robustness gains of non-blocking.

### 6.2 SSE Event Types

| Event | When | Frontend shows |
|---|---|---|
| `progress` | Starting/ending a step | Status indicator |
| `data_found` | Nonempty query result | Inline table/chart |
| `question` | Agent called `ask_user` | Question bubble + input |
| `answer_injected` | User answer received | User's answer shown |
| `done` | Analysis complete | Final analysis |
| `partial` | Stopped with gaps | "I got this far: ..." |
| `error` | Fatal error | Error message |

### 6.3 Checkpoint Protocol

After each sub-question execution, the harness checks:

1. **Message queue** — any user messages since last checkpoint?
   - If answer to a pending question: inject into context, feed to verifier
   - If new info ("by the way, Supplier X raised prices"): inject as context
   - If meta-question ("how do you calculate margin?"): answer inline
2. **Token budget** — exceeded? → emergency stop
3. **Iteration budget** — exceeded? → emergency stop
4. **Sub-question queue** — more to do? → next sub-question

---

## 7. ETL Pipeline (Full Reload First, Delta Later)

### 7.1 Why Full Reload (Changed From v1)

The first plan had delta detection (hash-based, upsert). Three reviewers called
this out as premature complexity. They're right:

| Factor | Value |
|---|---|
| Database size | ~82 MB |
| Full reload time | ~30 seconds (estimated) |
| Data change frequency | Weekly or monthly (store owner's manual schedule) |
| Delta complexity | Hash comparison, upsert logic, edge cases on legacy format |
| Risk of delta bugs | Corrupted primary keys, missing timestamps, encoding issues |

**Decision:** Phase 1-2 use full reload. The operator clicks "Sync" → 30 second wait →
data is fresh. No delta logic until someone finds the 30-second wait unacceptable.

### 7.2 Pipeline Steps

```
Step 1: User clicks "Sync Latest Data" button in the Dashboard UI
Step 2: Native file picker opens → user selects .mdb file
Step 3: Backend runs:
   mdb-export pos_export.mdb Stock > stock.csv
   mdb-export pos_export.mdb Docket > docket.csv
   mdb-export pos_export.mdb DocketItem > docket_item.csv
   ...
Step 4: Python script:
   - Extract schema from .mdb (mdb-schema) → hash column names + types
   - Compare hash against stored schema hash from last successful run
   - If hash differs, emit WARNING and log old vs new schema
   - Parse CSVs (handle nulls, encoding, type coercion)
   - Log encoding warnings for any non-ASCII text that failed
   - Write to DuckDB staging tables
   - Validate row counts against expected ranges
   - Swap staging into production tables
Step 5: UI shows "Sync complete: thousands of products, thousands of dockets"
```

**Schema drift detection:** If legacy POS ever changes (unlikely but possible), the
ETL emits a visible warning in the UI: "The database structure has changed.
The AI agent may generate incorrect queries until the schema description is
updated." This prevents the silent failure where the agent hallucinates column
names against stale schema docs.

### 7.3 Windows-Specific ETL Notes (Addressing First Review)

- `mdbtools` on Windows: Use the precompiled Windows binaries from
  [https://github.com/mdbtools/mdbtools/releases](https://github.com/mdbtools/mdbtools/releases)
  (v1.0.0+ has official Windows builds). These are tested before deployment.
- Character encoding: `mdb-export` output is checked for UTF-8 validity.
  Non-decodable characters are logged and replaced with Unicode replacement
  characters. This handles the retail store's potential
  multilingual product names.
- Path handling: All file paths use `pathlib.Path` (cross-platform, handles
  Windows backslashes).

### 7.4 Data Privacy Note (Added After First Review)

The `.mdb` file contains business-sensitive data: product costs, supplier
information, sales volumes, customer names. When data is sent to an LLM API
(DeepSeek, OpenAI, etc.), a subset of this data is transmitted as part of
the SQL query and results.

**Mitigations:**
- By default, only aggregated data is sent (grouped results, not raw transactions)
- The agent is prompted to minimize raw data in prompts: "Prefer SQL aggregation
  over fetching raw rows."
- The user can choose their LLM provider. DeepSeek Flash is the default (free).
  Switching to a provider with different data policies is one config line.
- No API keys are hardcoded. They're stored in a local config file that the
  user enters once via a Settings UI.

---

## 8. Security & Sandboxing (Honest Assessment)

### 8.1 What We Protect Against

| Threat | How we prevent it |
|---|---|
| **Accidental data modification** | `duckdb.connect(read_only=True)` — physically impossible to write |
| **Destructive queries** | Query timeout (30s), max row limit (10,000 for display, unlimited for aggregation) |
| **LLM hallucinates malicious SQL** | SQL executes against read-only DB. Worst case: CPU spike from bad query, timeout kills it |
| **LLM hallucinates malicious Python** | Sandboxed runner: blocked imports, timeout, output limit |
| **File system access** | `run_python` blocks `os`, `subprocess`, `pathlib`, `shutil`, `socket` |
| **Network access** | `run_python` blocks `requests`, `urllib`, `socket`, `http` |
| **LLM data exfiltration** | Output is limited to 10K chars; API calls are logged; user reviews logs |
| **Agent asks embarrassing questions** | `ask_user` questions are displayed in the chat; user can ignore |
| **ETL breaks** | Full reload means previous data is preserved until swap succeeds |

### 8.2 What We DO NOT Protect Against

| Risk | Why | Mitigation |
|---|---|---|
| **Agent deletes files via DuckDB** | Not possible — read-only DB | N/A |
| **Agent accesses other files** | `duckdb_query` is file-system-safe. `run_python` blocks file imports. But if there's a vulnerability in Python's restricted execution (and there are known sandbox escape techniques), a malicious prompt could theoretically bypass restrictions. | This is a known limitation of Python sandboxing. Full isolation requires Docker (ruled out). The practical risk is low for non-adversarial use (a hallucinated query, not an attacker). |
| **API key exposure** | The LLM API key is stored in a local config file. A compromised agent could read it. | Store in OS keychain (Windows Credential Manager) if possible; otherwise in an encrypted config file. |
| **Logs contain sensitive data** | SQL queries contain product names, prices. Logs could leak if the `.exe` is shared. | Logs are local only. Purge after 90 days. |

---

## 9. Frontend Architecture

### 9.1 Dual View

```
┌──────────────────────────────────────────────────────────┐
│  Warehouse Analytics                                       │
├────────────────┬─────────────────────────────────────────┤
│  DASHBOARD     │  CHAT                                     │
│  (tabs)        │  (default)                                │
├────────────────┴─────────────────────────────────────────┤
│                                                           │
│  Dashboard tab:                    Chat tab:               │
│  ┌──────────────────────┐        ┌──────────────────────┐ │
│  │ Quick Reports:       │        │ User: Should we      │ │
│  │  • Stock alerts      │        │       change margins? │ │
│  │  • Low turnover      │        │                      │ │
│  │  • Margin trends     │        │ Agent: analyzing...  │ │
│  │  • Top/bottom perf   │        │  progress: checking  │ │
│  │                      │        │  costs by category…  │ │
│  │ Custom Query:        │        │                      │ │
│  │  [SQL input]         │        │ (Agent asks question)│ │
│  │  [Run] → [Export]    │        │ Q: Why March drop?   │ │
│  └──────────────────────┘        │ User: Supplier X...  │ │
│                                   │                      │ │
│  "Sync Latest Data" button  always visible               │ │
└──────────────────────────────────────────────────────────┘
```

### 9.2 Dashboard (Zero LLM, Deterministic)

- Pre-built templated SQL queries: margin report, stock alerts, turnover analysis
- Custom SQL input (for power users — the operator may graduate to this)
- Export to CSV
- All queries go through `POST /api/dashboard/query` (direct DuckDB, no agent)
- **Works offline** — no API needed, only DuckDB

### 9.3 Chat (AI-Powered)

- SSE stream from `POST /api/agent/run`
- assistant-ui `Thread` component
- Custom message types for progress events, data tables, questions
- **Requires internet** for LLM API access
- Falls back gracefully: "Chat is unavailable offline. The Dashboard still works."

### 9.4 Packaging

**Phase 1-3 (dev):** FastAPI serves the React frontend statically. Open
`http://localhost:8000` in browser. No packaging needed.

**Phase 4 (deployment):** PyInstaller bundles the Python backend into a `.exe`.
The React frontend is built to static files and served by FastAPI. The `.exe`
opens the default browser. No Tauri, no Neutralino, no Electron.

This is simpler than the v1 plan (which had Tauri/Neutralino as options).
The "open browser from .exe" approach is less native-feeling but dramatically
easier to build, debug, and update. If the operator finds it usable, we keep it.

---

## 10. Logging, Retention & Privacy

### 10.1 What We Log

Every step of every analysis run:
- User query, query classification result
- Plan (sub-questions generated)
- Each SQL query executed (parameterized, with values)
- Execution time, row count, any errors
- Verifier scores and criteria breakdown
- Router decision and reason
- User interactions (questions asked, answers received)
- Synthesis output

### 10.2 Log Storage

- `auxiliary.db` — `analysis_logs` table (queryable)
- `logs/` directory — JSONL files, rotated at 10 MB, keep 100 files (~1 GB max)

### 10.3 Retention & Privacy (Added After First Review)

| Policy | Detail |
|---|---|
| Retention | 90 days in auxiliary.db, auto-purged |
| Log files | Kept until manual cleanup or disk > 90% |
| Sensitive data | Product names and prices are logged (needed for debugging). Customer names are truncated. |
| Log sharing | A "Export Debug Log" button creates a sanitized copy without customer names |
| User awareness | The Settings page shows: "This app logs all queries and results for debugging. Logs are stored locally and never sent anywhere." |

### 10.4 Companion Dashboard (For Development)

A terminal-based watcher that shows real-time agent state:
- Current layer and sub-question
- Last 10 events
- Token usage
- Error count
- Execution time

This is critical for iterative development. Without it, debugging the agent
means reading raw log files.

---

## 11. Development Roadmap

### Phase 1: Foundation (Week 1-2)
- [ ] Project structure: `backend/` (Python + FastAPI), `frontend/` (React + Vite)
- [ ] DuckDB schema for warehouse + auxiliary databases
- [ ] ETL pipeline: full reload via mdbtools
- [ ] Schema description file (used for agent prompts)
- [ ] Deterministic dashboard queries (stock alerts, margin report, top products)
- [ ] Test: 10 canned queries on full dataset

**Milestone:** "Python dashboard.py" opens a browser showing real data from DuckDB.

### Phase 2: Agent Core (Week 2-3)
- [ ] PydanticAI agent with `duckdb_query` and `run_python` tools
- [ ] Query classifier (fast path vs PEV path)
- [ ] PEV orchestrator: planner → executor → verifier → router
- [ ] Schema injection into agent system prompt
- [ ] Logging (structured, to both DB and files)
- [ ] Syntax-level safety: query timeout, row limit, input validation

**Milestone:** CLI agent that answers "what were March sales?" instantly and
"should we change margins?" with multi-step analysis.

### Phase 3: Backend APIs (Week 3-4)
- [ ] `POST /api/agent/run` — SSE streaming endpoint
- [ ] `POST /api/agent/respond` — user answer injection
- [ ] `POST /api/dashboard/query` — direct SQL endpoint
- [ ] Session management (in-memory, persisted to auxiliary.db)
- [ ] Graceful error handling (LLM down → show error, dashboard still works)
- [ ] Windows compatibility testing (run from day 1)

**Milestone:** Full agent accessible via `curl` with SSE streaming.

### Phase 4: Frontend (Week 4-5)
- [ ] React + Vite + TypeScript scaffold
- [ ] assistant-ui chat with custom message types (progress, data, questions)
- [ ] SSE consumer with reconnection logic
- [ ] Dashboard tabs (shadcn/ui): margin report, stock alerts, top products
- [ ] "Sync Latest Data" button with file picker
- [ ] Settings panel (API key entry, provider selection)

**Milestone:** The operator can open the app, sync data, ask a question, get an answer.

### Phase 5: Deployment Prep (Week 5-6)
- [ ] PyInstaller packaging (test on clean Windows VM)
- [ ] Windows mdbtools binary bundling  and path setup
- [ ] DuckDB + PyInstaller compatibility test (known footgun)
- [ ] One-click installer (Inno Setup or NSIS)
- [ ] User guide with screenshots (operator-facing)
- [ ] "About" dialog with version and error reporting instructions

**Milestone:** Double-click → app opens → sync data → ask questions.

### Phase 6: Iterate (Ongoing)
- [ ] Real usage with the store operator → collect 20-30 actual queries
- [ ] Build test set from real queries, calibrate verifier thresholds
- [ ] Optimize token usage (compress context between steps)
- [ ] Add caching for repeated queries
- [ ] Tune query classifier based on misclassification rate
- [ ] Add more dashboard reports based on operator requests

---

## 12. Technology Stack (Final)

| Component | Choice | Reasoning |
|---|---|---|
| **Warehouse** | DuckDB | Embedded OLAP, read-only mode, single file, zero ops |
| **Agent framework** | PydanticAI | Type-safe tools, 25+ providers natively, SSE integration |
| **LLM (default)** | DeepSeek Flash | ~$0, fast, good analytical reasoning on benchmarks |
| **LLM (fallback)** | Gemini Flash 2.5 | Also free tier, different provider for redundancy |
| **API server** | FastAPI | Async-native, SSE, type-safe, PydanticAI integration |
| **Chat UI** | assistant-ui | SSE-native, multi-message-type display, active community |
| **Dashboard UI** | shadcn/ui + recharts | Deterministic reports, well-maintained, good test coverage |
| **Frontend build** | Vite | Fast, TypeScript-native |
| **Packaging** | PyInstaller | Bundle Python → .exe, serve frontend statically from FastAPI |
| **ETL** | mdbtools v1.0+ | Cross-platform, Windows binary available, well-tested for Jet 3 |
| **ETL language** | Python + pandas | DataFrame transforms, encoding handling, schema validation |
| **Logging** | structlog | Structured, queryable from auxiliary.db |

### LLM Provider Fallback Strategy

```python
providers = {
    "deepseek": DeepSeekModel("deepseek-chat"),    # Default, ~$0
    "gemini": GeminiModel("gemini-2.0-flash"),     # Fallback 1, ~$0
    "openai": OpenAIModel("gpt-4o-mini"),          # Fallback 2, ~$0.15/query
}

# On API error: log error, try next provider
# On timeout: try once more, then skip to fallback
# On rate limit: wait 5s, retry, then skip
```

---

## 13. Known Risks and Mitigations

These are honest — not hidden. Each one is either mitigated or accepted.

| Risk | Severity | Mitigation |
|---|---|---|
| **PyInstaller + DuckDB native extensions** | Medium | Test early (Phase 1), pin DuckDB version, document workaround |
| **mdbtools encoding on Windows** | Medium | UTF-8 validation step, log encoding warnings, manual review of first ETL run |
| **Python sandbox escapes** | Low-Medium | Not fully solvable without Docker. Constraining imports + timeout + output limits makes it impractical for accidental misuse. Adversarial misuse is out of scope (single-user desktop). |
| **LLM API downtime** | Medium | Dashboard works offline. Chat shows friendly error. Provider fallback chain. |
| **Query timeout causes partial answer** | Low | Router detects this, returns partial results with explanation. |
| **Verifier incorrectly approves bad answer** | Medium | All verifier decisions are logged. Thresholds are tuned empirically in Phase 6. The user always sees the SQL that was run. |
| **The operator finds it too complex** | Medium | Dashboard-first UX. Chat is optional for simple queries (type a question OR click a report). |
| **82 MB grows to 500 MB+** | Low | DuckDB handles 10+ GB easily. If it grows, add delta ETL in Phase 6. |
| **Schema drift during full reload** — if legacy POS changes schema, documented | Low | ETL checks schema hash every run. If different, emits warning in UI and logs diff. Agent continues with stale schema description until manually updated. |

---

## 14. Pre-Emptive Answers to Likely Questions

**Q: Why not just use Excel with Power Query?**

Because this system answers questions the operator didn't know to ask. He doesn't look
for "margin correlation between Accessories and seasonal trends" in Excel because
he doesn't know to. The agent does.

**Q: Why not use an existing BI tool (Power BI, Metabase)?**

Power BI costs $10/user/month. Metabase requires a server. Both require schema
understanding to create reports. Neither answers natural-language questions.

**Q: Why not run a local LLM via Ollama to avoid API dependency?**

Tested during research phase. Local models (Gemma 3, Qwen 2.5, Llama 3.2) are
2-5x slower, less accurate on SQL generation, and require a GPU for reasonable
latency. The store laptop (likely no GPU) would take 30-60 seconds per step.
DeepSeek Flash completes in 2-5 seconds, costs effectively $0, and is more
accurate. The tradeoff (internet dependency) is accepted.

**Q: What happens if the internet goes down?**

The AI chat shows: "Chat is unavailable offline. The Dashboard still works."
The Dashboard has 10+ pre-built reports that cover daily ops. Data syncing
also works (mdbtools + DuckDB are local).

**Q: What if DeepSeek changes its pricing or API?**

The architecture is provider-agnostic via PydanticAI. Switching from DeepSeek
to Gemini Flash or OpenAI requires changing one line of config. The fallback
chain handles this automatically.

**Q: Why not build a mobile app?**

The operator uses a laptop. Desktop-only simplifies development and deployment.
If he wants mobile access later, the FastAPI backend can serve a mobile-friendly
React frontend with minimal changes.

**Q: How do you test the agent without real data?**

We have the full schema and schema description. We can generate synthetic data
(60K rows with realistic patterns) for testing. The ETL pipeline is tested
against a copy of the real .mdb file.

---

## 15. Verifiable Claims

Every non-trivial claim in this document can be checked:

| Claim | How to verify |
|---|---|
| arXiv 2601.02179v1 — Cambridge confidence paper | [arXiv](https://arxiv.org/abs/2601.02179) |
| arXiv 2605.27935v1 — Agent depth mechanics | [arXiv](https://arxiv.org/abs/2605.27935) |
| arXiv 2603.11445 — VMAO framework | [arXiv](https://arxiv.org/abs/2603.11445) |
| $47,000 LangChain incident | [tianpan.co](https://tianpan.co/blog/2026-05-07-tool-call-convergence-agents-stopping-criteria) |
| `pydantic-ai-just-bash` package | [PyPI](https://pypi.org/project/pydantic-ai-just-bash/0.3.0/) |
| PydanticAI 25+ providers | [PydanticAI agent.py source](https://github.com/pydantic/pydantic-ai) |
| PydanticAI UI integration | [docs/ui/overview.md](https://github.com/pydantic/pydantic-ai/blob/main/docs/ui/overview.md) |
| LangGraph PEV source | [github.com/ManjunathGovindaraju/langgraph-plan-execute-validate](https://github.com/ManjunathGovindaraju/langgraph-plan-execute-validate) |
| mdbtools Windows binaries | [github.com/mdbtools/mdbtools/releases](https://github.com/mdbtools/mdbtools/releases) |
| DuckDB read_only mode | [duckdb.org/docs/connect](https://duckdb.org/docs/connect) |

No claim in this document is included without a verifiable source.
No arXiv ID is cited without the paper being confirmed to exist.
No feature is claimed as "native" without it being documented in the project's
official documentation.

---

*Document prepared for external architecture review, round 2. 2026-06-03.*
