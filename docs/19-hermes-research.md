# 19 — Hermes Agent: Deep Research

> Research conducted 2026-08-04 against three primary sources. Every claim below is marked with its
> evidence class. **Nothing in this document is reconstructed from the name of a feature.** Where the
> published documentation is silent, this document says so rather than filling the gap — a labelled
> gap is a research result; a plausible paragraph is a liability.
>
> **Sources**
> - `S1` — Official docs: <https://hermes-agent.nousresearch.com/docs>
> - `S2` — GitHub: <https://github.com/NousResearch/hermes-agent>
> - `S3` — DeepSeek integration guide: <https://api-docs.deepseek.com/quick_start/agent_integrations/hermes>
>
> **Evidence classes**
> | Class | Meaning |
> |---|---|
> | ✅ **Verified** | Stated explicitly in S1/S2/S3, quoted or paraphrased faithfully |
> | ◐ **Inferred** | Follows necessarily from two or more verified facts; the inference is shown |
> | ⛔ **Not found** | Searched for and not present in the published documentation as of 2026-08-04 |

---

## 0. What Hermes Agent is, in one paragraph

Hermes Agent is an **MIT-licensed, self-hosted, general-purpose AI agent runtime** built by Nous
Research (v0.20.0 at time of research). It is a single `AIAgent` core wrapped by six entry points
(CLI, messaging gateway, ACP/IDE adapter, batch runner, API server, Python library), with 70+ tools
across ~28 toolsets, SQLite-backed sessions, a skills system, bounded persistent memory, MCP client
support, a cron scheduler, subagent delegation, seven execution backends, and adapters for 30+
messaging platforms. It is explicitly positioned as *"the self-improving AI agent"* — it writes and
refines its own skills, and nudges itself to persist knowledge. ✅ S1, S2

**The single most important framing for our purposes:** Hermes is a **general agent runtime**, not a
pipeline orchestrator. Its cost profile, context management, and control flow are all designed for
open-ended conversational and investigative work. That is a genuinely different shape from a
1,200-item classification funnel, and §26 quantifies the difference.

---

## 1. Runtime Architecture ✅

Six entry points converge on one core (S1, *Developer Guide → Architecture*):

```
CLI (cli.py)   Gateway (gateway/run.py)   ACP (acp_adapter/)   Batch Runner   API Server   Python Library
      └──────────────┴───────────┬───────────┴──────────────┴─────────────┴──────────────┘
                                 ▼
                    AIAgent  (run_agent.py)  ── the single core
                                 │
        ┌────────────────────────┼────────────────────────┐
        ▼                        ▼                        ▼
  Prompt Builder          Provider Resolution        Tool Dispatch
  (prompt_builder.py)     (runtime_provider.py)      (model_tools.py)
```

The documented conversation cycle, verbatim:

> "User input → HermesCLI.process_input() → AIAgent.run_conversation() →
> prompt_builder.build_system_prompt() → runtime_provider.resolve_runtime_provider() →
> API call (chat_completions / codex_responses / anthropic_messages) → tool_calls? →
> model_tools.handle_function_call() → loop → final response → display → save to SessionDB"

Three stated design constraints (verbatim):

> "**Prompt stability:** System prompt doesn't change mid-conversation."
> "**Observable execution:** Every tool call is visible via callbacks."
> "**Platform-agnostic core:** One AIAgent class serves CLI, gateway, ACP, batch, and API server."

**Why this matters to us.** "Platform-agnostic core" plus "Python Library" as a first-class entry
point means Hermes can be embedded, not only shelled out to. And `hermes -z "<prompt>"` gives a
clean headless contract: *"single prompt in, final response text out, nothing else on stdout or
stderr"* — with `--usage-file` writing *"a machine-readable usage report after the run"* including
tokens, cost and model metadata. That is the integration primitive our cost accounting needs. ✅ S1

---

## 2. Internal Components ✅

| Component | File | Responsibility |
|---|---|---|
| `AIAgent` | `run_agent.py` | The conversation loop |
| Prompt builder | `agent/prompt_builder.py`, `system_prompt.py` | Ordered system-prompt tiers |
| Context engine | `agent/context_engine` | Pluggable context assembly |
| Context compressor | `context_compressor.py` | Summarisation under token pressure |
| Prompt caching | `prompt_caching.py` | Cache-control breakpoint insertion (§26) |
| Provider resolver | `runtime_provider.py` | `(provider, model)` → `(api_mode, api_key, base_url)`; 18+ providers, OAuth, credential pools, alias resolution |
| Tool registry | `tools/registry.py` | *"70+ registered tools across ~28 toolsets. Each tool file self-registers at import time."* |
| Session store | `hermes_state.py`, `gateway/session.py` | SQLite + FTS5 |
| Gateway | `gateway/` | *"25+ platform adapters"* |

Top-level repository layout ✅ S2: `agent/ apps/ skills/ tools/ plugins/ providers/ gateway/
hermes_cli/ web/ ui-tui/ tests/ tests-js/ docker/ docs/ scripts/ nix/ locales/ optional-mcps/
optional-skills/ website/`, plus `.env.example`, `cli-config.yaml.example`, `pyproject.toml`,
`package.json`, `flake.nix`, `docker-compose.yml`.

**`docker-compose.yml` exists in the repo root** ✅ S2 — relevant to §21–23, although the
installation documentation page itself does not cover Docker deployment ⛔.

---

## 3. Tool Calling ✅

- Tools live in `tools/`, self-register at import into `tools/registry.py`, and are grouped into
  toolsets. ✅
- Documented toolset families: web (`web_search`, `web_extract`), X search (`x_search`), terminal &
  files (`terminal`, `process`, `read_file`, `patch`), browser (`browser_navigate`,
  `browser_snapshot`, `browser_vision`), media (`vision_analyze`, `image_generate`,
  `text_to_speech`), agent orchestration (`todo`, `clarify`, `execute_code`, `delegate_task`),
  memory (`memory`, `session_search`), automation (`cronjob`), integrations (`ha_*`, MCP). ✅
- Toolsets are selected per invocation with `hermes chat --toolsets "web,terminal"`, configured
  interactively with `hermes tools`, and **suppressed globally** with:
  ```yaml
  agent:
    disabled_toolsets:
      - memory
      - web
  ```
  ✅ S1 (*Configuration*). This key is load-bearing for our cost design — see §26.
- **Token cost of tool definitions is not documented.** ⛔ The docs never state how many tokens the
  70-tool schema block occupies. ◐ **Inferred**: a JSON-schema definition for a non-trivial tool is
  typically 100–400 tokens; 70 tools therefore plausibly occupies 7k–25k tokens *per request*
  unless toolsets are pruned. This inference is why `disabled_toolsets` is treated as mandatory
  configuration rather than tuning in [24 §3](24-cost-optimization.md), and why the number must be
  **measured** in Phase H1 rather than assumed.

---

## 4. Skills ✅

A skill is *"an on-demand knowledge document the agent can load when needed"*, following *"a
progressive disclosure pattern to minimize token usage"*, compatible with the **agentskills.io** open
standard. ✅

`SKILL.md` format, verbatim from S1:

```yaml
---
name: my-skill
description: Brief description of what this skill does
version: 1.0.0
platforms: [macos, linux]
metadata:
  hermes:
    tags: [python, automation]
    category: devops
    fallback_for_toolsets: [web]
    requires_toolsets: [terminal]
    config:
      - key: my.setting
        description: "What this controls"
        default: "value"
        prompt: "Prompt for setup"
---
# Skill Title
## When to Use
## Procedure
## Pitfalls
## Verification
```

Directory layout ✅:

```
~/.hermes/skills/
├── category/
│   ├── skill-name/
│   │   ├── SKILL.md
│   │   ├── references/
│   │   ├── templates/
│   │   ├── scripts/
│   │   ├── examples/
│   │   └── assets/
```

External directories are configurable ✅:

```yaml
skills:
  external_dirs:
    - ~/.agents/skills
    - /home/shared/team-skills
```

Additional verified facts:

- **Secrets declaration.** `required_environment_variables` in frontmatter; *"Once set, declared env
  vars are automatically passed through to `execute_code` and terminal sandboxes."*
- **Conditional activation.** `fallback_for_toolsets`, `requires_toolsets`, `fallback_for_tools`,
  `requires_tools` show/hide a skill by tool availability.
- **Platform gating.** `platforms: [linux]` hides the skill from *"the system prompt, `skills_list()`,
  and slash commands on incompatible platforms."*
- **Bundles.** `~/.hermes/skill-bundles/<slug>.yaml` groups skills under one slash command with a
  shared `instruction:` block. *"Bundles take precedence over individual skills when slugs collide."*
- **Media directives.** `[[as_document]]` and `[[audio_as_voice]]`; bare absolute file paths in a
  response auto-extract as attachments.

---

## 5. Skill Discovery ✅

- **Automatic.** Skills in `~/.hermes/skills/` are discovered without registration.
- **Slash commands.** `/skill-name args`; multiple skills stack in one message
  (`/github-pr-workflow /test-driven-development fix issue #123`).
- **Natural language.** The model selects a skill from the Level-0 metadata list.
- **`skills_list()`** returns `[{name, description, category}, ...]`.

---

## 6. Skill Loading ✅ — the three levels

This is the most important efficiency mechanism in Hermes and is stated numerically:

| Level | Call | Loads | Documented cost |
|---|---|---|---|
| 0 | `skills_list()` | `{name, description, category}` for every skill | **~3k tokens** |
| 1 | `skill_view(name)` | The full `SKILL.md` | Skill-dependent |
| 2 | `skill_view(name, path)` | A specific reference file | File-dependent |

> "The agent only loads the full skill content when it actually needs it."

**Design consequence for us.** Level 0 is paid on *every* turn. ◐ **Inferred**: skill *count* and
*description length* are therefore a permanent per-turn tax, while skill *body* length is free until
used. This inverts the usual instinct — it is better to have 15 skills with 12-word descriptions and
long bodies than 60 skills with paragraph descriptions and short bodies.
[22 §2](22-hermes-skills.md) makes this a hard authoring rule.

---

## 7. Memory ✅

Two bounded files plus an unbounded searchable transcript store.

| Store | Path | Limit | Mechanism |
|---|---|---|---|
| `MEMORY.md` | `~/.hermes/memories/` | **2,200 chars (~800 tokens)** | Agent's own notes |
| `USER.md` | `~/.hermes/memories/` | **1,375 chars (~500 tokens)** | User profile |
| Sessions | `~/.hermes/state.db` | Unbounded | SQLite + **FTS5** |

Both files are *"injected into the system prompt as a frozen snapshot at session start."* ✅

The `memory` tool supports `add`, `replace` (substring match via `old_text`), `remove`. On overflow
the tool returns an error — *"Adding this entry (250 chars) would exceed the limit. Consolidate
now."* — forcing the agent to consolidate. ✅

`session_search` is FTS5 over all past sessions. The documentation's own comparison, verbatim:

| Feature | Persistent Memory | Session Search |
|---|---|---|
| Capacity | ~1,300 tokens | Unlimited (all sessions) |
| Speed | Instant | ~20ms FTS5 query |
| Cost | Token cost per prompt | **Free — no LLM calls** |

> "Memory is for critical facts that should always be in context. Session search is for 'did we
> discuss X last week?' queries."

Config ✅:

```yaml
memory:
  memory_enabled: true
  user_profile_enabled: true
  memory_char_limit: 2200
  user_char_limit: 1375
  write_approval: false
```

Security ✅: memory entries are *"security scanned for injection and exfiltration patterns before
being accepted, since they're injected into the system prompt"*; exact duplicates are rejected.

**The `/journey` command** gives a timeline of what Hermes has learned, with
`hermes journey list | delete <node> | edit <node>` — *"prune and correct"*. ✅

---

## 8. Knowledge Management ✅ / ◐

Hermes has **no first-class knowledge-base primitive**. ⛔ There is no bounded-schema, versioned,
evidence-carrying knowledge store analogous to our BKB. What exists:

| Mechanism | Fit for structured business knowledge |
|---|---|
| `MEMORY.md` (800 tokens) | Far too small; unstructured; no versioning, evidence, or origin |
| Skills | Procedures, not facts; but excellent for *"how to query the knowledge base"* |
| Context files (`AGENTS.md`) | Static instructions; no lifecycle, no per-section versioning |
| External memory providers (Honcho, Mem0, Hindsight, +5) | *"knowledge graphs, semantic search, automatic fact extraction"*, running *"alongside built-in memory (never replacing it)"* ✅ |
| MCP servers | Arbitrary external knowledge exposed as tools ✅ |

◐ **Inferred, and decisive**: the correct home for our 23-section BKB is **our own SQLite schema,
exposed to Hermes as a tool**, not Hermes memory. This is developed in
[23 — Memory & Knowledge Strategy](23-hermes-memory-and-knowledge.md).

---

## 9. Profiles ✅

*"Multiple isolated Hermes instances, each with its own config, sessions, skills, and home
directory."* Selected by `HERMES_HOME` or `hermes -p <name>`. Each profile gets its own
`config.yaml`, `.env`, `auth.json`, memories, skills, sessions, logs. ✅

CLI: `hermes profile create | delete | list | use | clone | export | import`. ✅

**Profile routing** ✅ S2 (`docs/profile-routing.md`) lets *one* gateway serve many profiles:
routes in `config.yaml` under `profile_routes`, discriminated by platform (required), guild ID, chat
ID, thread ID, matched conjunctively with specificity weights (thread 8 > channel 4 > guild 2).
*"Each profile keeps fully isolated state (`MEMORY.md`, `USER.md`, `SOUL.md`, sessions, tools)."*

**Critical limitation for multi-agent designs:** profile isolation is *total*. Two profiles share no
memory and no sessions. Any cross-profile knowledge must travel through an external store — for us,
the platform database.

---

## 10. Context Files ✅

| File | Purpose | Discovery |
|---|---|---|
| `.hermes.md` / `HERMES.md` | Project instructions (highest priority) | Walks to git root |
| `AGENTS.md` | Project instructions, conventions, architecture | CWD + subdirectories |
| `CLAUDE.md` | Claude Code context | CWD + subdirectories |
| `SOUL.md` | Global personality | **`HERMES_HOME` only** |
| `.cursorrules` | Cursor conventions | CWD only |
| `.cursor/rules/*.mdc` | Cursor rule modules | CWD only |

> "Only **one** project context type is loaded per session (first match wins): `.hermes.md` →
> `AGENTS.md` → `CLAUDE.md` → `.cursorrules`. **SOUL.md** is always loaded independently."

Size limits ✅: `context_file_max_chars` when set, otherwise dynamic with a **floor of 20,000 and a
ceiling of 500,000 characters**; head truncation 70%, tail 20%; progressive-discovery cap **8,000
characters per file**.

**Progressive subdirectory discovery** ✅: a `SubdirectoryHintTracker` watches tool calls and appends
a nested `AGENTS.md` *to the tool result* rather than to the system prompt — the documentation states
this exists specifically to avoid *"system prompt bloat"* and to preserve *"prompt cache
preservation."* That phrase is direct evidence that prompt-cache stability is an explicit design
concern inside Hermes.

All context files are **prompt-injection scanned** before inclusion; a detected file is replaced with
`[BLOCKED: filename contained potential prompt injection. Content not loaded.]` ✅

---

## 11. AGENTS.md ✅

The primary project context file. Discovered from CWD and subdirectories, loaded into the system
prompt at startup, and progressively injected for subdirectories during a session. Importable from
OpenClaw via `hermes claw migrate`. ✅

**Guidance from S1 (*Tips*), verbatim:** *"Create an `AGENTS.md` in your project root with
architecture decisions, coding conventions, and project-specific instructions. This is automatically
injected into every session."* … *"Keep context files focused and concise. Every character counts
against your token budget since they're injected into every single message."*

---

## 12. SOUL.md ✅

Persona / identity file. Located **only** at `~/.hermes/SOUL.md` or `$HERMES_HOME/SOUL.md` —
*"Hermes loads it only from `HERMES_HOME` and does not probe the working directory for it."* Controls
*"the agent's personality, tone, and communication style."* Referred to in the configuration docs as
**"system prompt slot #1"** — i.e. it sits at the very head of the prompt, in the stable tier. ✅

Swappable presets via `/personality [name]`. ✅

---

## 13. MCP ✅

Config lives in `~/.hermes/config.yaml` under `mcp_servers`. Two transports:

```yaml
mcp_servers:
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "***"
  remote_api:
    url: "https://mcp.example.com/mcp"
    headers:
      Authorization: "Bearer ***"
```

- OAuth 2.1 supported via `auth: oauth` — *"Hermes handles discovery, dynamic client registration,
  PKCE, token exchange, refresh, and step-up auth."* ✅
- mTLS via `client_cert` / `client_key`. ✅
- Tools are namespaced `mcp_<server>_<tool>` — e.g. `mcp_filesystem_read_file`. ✅
- Per-server `tools.include` / `tools.exclude` filtering; `tools.resources` / `tools.prompts` disable
  the utility wrappers. ✅
- **Stdio env filtering:** only `PATH, HOME, USER, LANG, LC_ALL, TERM, SHELL, TMPDIR` plus `XDG_*`
  and explicitly configured `env` reach the subprocess. ✅
- MCP error messages are **credential-redacted** before returning to the LLM (`ghp_…`, `sk-…`,
  bearer tokens, `token=`, `key=`, `password=`). ✅
- **Token cost of MCP tool schemas: not documented.** ⛔ ◐ Same inference as §3 applies — every MCP
  tool adds a permanent per-turn schema cost, so an MCP server should be added only when its tools
  are genuinely used.

---

## 14. Messaging Gateway ✅

- **30+ platforms**: Telegram, Discord, Slack, WhatsApp, Signal, SMS, Email, Teams, Matrix, DingTalk,
  Feishu/Lark, WeCom, Weixin, iMessage, QQ, LINE, ntfy, Home Assistant, and others.
- **Runs as a daemon**: `hermes gateway install | start | stop | restart | status`; systemd on Linux
  (`--system` for boot-time), launchd on macOS (`~/Library/LaunchAgents/ai.hermes.gateway.plist`);
  `hermes gateway run` for foreground. Services are scoped to `HERMES_HOME`, so multiple profiles get
  separate service names. `--all` acts on every profile's gateway. ✅
- **Authorisation order** ✅: per-platform allow-all → DM-pairing approved list → platform allowlist
  → global allowlist → global allow-all → **default deny**.
- **DM pairing** ✅: 8-character code from a 32-char unambiguous alphabet (no `0/O/1/I`),
  cryptographically random, **1-hour TTL**, rate-limited to 1 request per user per 10 minutes,
  5 failed attempts → 1-hour lockout, `chmod 0600` on all pairing data in `~/.hermes/pairing/`.
  Approve with `hermes pairing approve telegram XKGH5N7P`.
- **Two-tier permissions** ✅: admins get full command access; regular users only explicitly enabled
  slash commands.
- **Durable delivery ledger** in `state.db` — redelivery after a crash is marked
  *"♻️ Recovered reply"*. ✅
- **Intentional silence** ✅: a response of exactly `[SILENT]`, `SILENT`, `NO_REPLY`, or `NO REPLY`
  suppresses delivery while keeping the turn in the transcript.
- **Per-channel model overrides** ✅:
  ```yaml
  platforms:
    discord:
      channel_overrides:
        "123456789012345678":
          model: anthropic/claude-sonnet-4.6
          system_prompt: "You are the #dev specialist."
  ```
- **Session reset policy** ✅:
  ```yaml
  session_reset:
    mode: idle        # idle | daily | both | none
    idle_minutes: 1440
    at_hour: 4
  ```

### 14.1 `hermes send` — the zero-LLM outbound path ✅

> "**`hermes send`** — Send a one-shot message to a configured messaging platform **without spinning
> up an agent or gateway loop**." … "Designed for shell scripts, cron jobs, CI hooks, and monitoring
> daemons."
>
> Flags: `-t/--to <platform:chat_id>`, `-f/--file <path>`, `-q/--quiet`.

**This is the single most valuable Hermes capability for this project**, and the reason is economic
rather than functional: it delivers Telegram output at **zero token cost**. Every deterministic
notification we emit — run complete, new high-confidence lead, cost warning, daily digest, gate
reached — is rendered by SQL and pushed with `hermes send`. See [24 §5](24-cost-optimization.md).

---

## 15. Telegram ✅

Setup: create a bot with **@BotFather** (`/newbot`), obtain a token of the form
`123456789:ABCdefGHIjklMNOpqrSTUvwxYZ`. Find your numeric user ID with @userinfobot.

`~/.hermes/.env`:
```
TELEGRAM_BOT_TOKEN=<token>
TELEGRAM_ALLOWED_USERS=123456789
```

`~/.hermes/config.yaml`:
```yaml
telegram:
  require_mention: true
  exclusive_bot_mentions: true
  mention_patterns: []
  ignored_threads: []
  reactions: true
  group_allow_from: []
  group_allowed_chats: []
  guest_mode: false
```

Verified capabilities: **inline buttons** (the `clarify` tool renders preset choices as an inline
keyboard: `[1. Option] [2. Option] [✏️ Other]`), **reactions** (👀 processing → ✅ / ❌), **slash
commands** (menu from a central registry, capped at 60 by default, configurable 1–100), **streaming**
(`editMessageText`, or native `sendMessageDraft` on Bot API 9.5+), **rich messages** (tables, task
lists, details blocks, block math via `sendRichMessage` on Bot API 10.1+), **voice** in and out,
**file attachments**, and **forum topics** for multi-session separation. ✅

**One correction worth stating precisely, because the obvious reading is wrong.** Inline buttons are
rendered by the **`clarify` tool**, which is an *agent* tool — it costs a model turn. They are
therefore available on **agent-initiated clarification**, and **not** on a message pushed with
`hermes send`. Our gate cards are deliberately text plus a slash command, because that path costs
nothing ([21 §7.2](21-hermes-architecture.md)). Inline buttons appear only when the operator is
already in a conversation and the agent asks a question.

**Two things the `hermes send` documentation does not settle** ⛔, both of which decide the transport
design once the platform and Hermes run in separate containers
([21 §8.1](21-hermes-architecture.md)):

1. **Is send reachable over `hermes serve` (JSON-RPC/WebSocket) or the API server**, or is it
   CLI-only? A CLI-only form cannot be invoked across a container boundary.
2. **Does `hermes send` write into the session transcript?** If it does, the agent knows what it told
   the operator and `session_search` can find it; if not, a direct Bot API call from the platform
   loses nothing.

Both are measured as **M-9** and **M-10** in [25 §4.1](25-hermes-roadmap.md), during H1, before any
design depends on the answer.

---

## 16. Scheduling ✅

| Property | Value |
|---|---|
| Storage | `~/.hermes/cron/jobs.json`, atomic writes |
| Output | `~/.hermes/cron/output/{job_id}/{timestamp}.md` |
| History | `~/.hermes/cron/executions.db` |
| Tick | **The gateway ticks the scheduler every 60 seconds**, running due jobs in *isolated agent sessions* |
| Lock | `~/.hermes/cron/.tick.lock` prevents overlapping ticks double-running a batch |
| Creation | `/cron add "every 2h" "..."`, `hermes cron create`, or the `cronjob` tool |
| Manual tick | `hermes cron tick` — *"Run due jobs once and exit"* |

Schedule formats ✅: relative one-shot (`30m`, `2h`, `1d`), intervals (`every 30m`), cron expressions
(`0 9 * * *`, `0 9 * * 1-5`), ISO timestamps (`2026-03-15T09:00:00`).

Skills attach to jobs ✅:
```
cronjob(action="create", skill="blogwatcher",
        prompt="Check feeds...", schedule="0 9 * * *")
```
…or `skills=["blogwatcher", "maps"]` — *"Skills are loaded in order. The prompt becomes the task
instruction layered on top of those skills."*

Delivery ✅: `deliver:` accepts `origin`, `local`, `telegram`, `discord`, `slack`, `whatsapp`,
`email`, …, `all`, or a comma-separated fan-out. `cron.wrap_response: false` disables header/footer
wrapping.

Model resolution ✅: **per-job pin → `cron.model` → global default**, and — importantly —
*"The agent's `cronjob` tool cannot set or change per-job models — inference pins are user-owned."*
A **drift guard** (`cron.model_drift_guard`, default on) stops unpinned jobs silently inheriting a
paid provider switch.

Reliability ✅: execution states `claimed | running | completed | failed | unknown`, recorded
*before* provider dispatch. After a restart an abandoned attempt is marked `unknown` *"only when the
original PID and process-start fingerprint prove that its owner is gone."* Jobs with `workdir` set
run **sequentially**; jobs without it are parallelised.

**Every cron job is a full fresh agent session.** ◐ Inferred cost consequence: a job's cost is
(system prompt + skills level-0 + attached skill bodies + prompt) × turns. Frequent cron jobs are
therefore the second-largest agent-tier cost driver after conversation, and [24 §5](24-cost-optimization.md)
routes most of ours through `hermes send` instead.

---

## 17. Delegation ✅

`delegate_task(goal=..., context=...)`, or batch form `delegate_task(tasks=[{goal, context}, ...])`.
Optional `max_iterations` (default **50**), `role` (`leaf` | `orchestrator`), `background=true`.

| Property | Value |
|---|---|
| Concurrency | *"Up to 3 concurrent subagents by default (configurable, no hard ceiling)"* — `max_concurrent_children` |
| Nesting | `max_spawn_depth`, **default 1** (flat only). At depth 3 × 3 children → *"3×3×3 = 27 concurrent leaf agents"* |
| Context | *"Subagents start with a completely fresh conversation. They have zero knowledge of the parent's conversation history"* |
| Tools | Leaf subagents **cannot** call `delegate_task`, `clarify`, `memory`, `send_message`, `cronjob`. Orchestrators keep `delegate_task`. Both keep `execute_code` |
| Return | *"Only the final summary enters the parent's context"* |
| Cost | *"Higher (full LLM loop)"* per child; parallel batches multiply spend |

---

## 18. Parallel Agents ✅

Two distinct parallelism mechanisms, and they are **not** interchangeable:

1. **`delegate_task`** — up to N concurrent LLM loops. Good for genuinely open-ended parallel
   investigation. Expensive: full reasoning loop per child.
2. **`execute_code`** — one Python script, one LLM turn, arbitrary internal parallelism, with
   *"intermediate tool results never enter the context window."* Good for known-shape bulk work.

The documentation is explicit that `execute_code` is the cheaper of the two, and that the agent
should reach for it *"for workflows with 3+ tool calls with processing logic between them, bulk data
filtering or conditional branching, loops over results."* ✅

**This distinction is the backbone of our agent design.** Our pipeline is known-shape; it belongs in
`execute_code`-style single-turn invocation of custom tools, never in a delegation tree.

---

## 19. Agent Communication ✅

> "Subagents cannot interact directly. Communication flows one-way: parents provide context at
> delegation time; children return only a structured summary. **No cross-agent messaging exists.**"

Profiles are likewise fully isolated (§9). ◐ **Inferred**: any multi-agent design requiring shared
state must route it through an external store. For us that is the platform's SQLite database, reached
over the platform's localhost HTTP API — never by two processes writing the same file.

---

## 20. Long-Running Workflows ✅ / ◐

Mechanisms that exist:

| Need | Mechanism | Class |
|---|---|---|
| Survive restart | Session `resume_pending`, `.clean_shutdown` marker, `suspend_recently_active()` | ✅ |
| Avoid infinite restarts | Sessions active across 3+ consecutive restarts are auto-suspended | ✅ |
| Long jobs | `background=true` on `delegate_task` returns a handle; results post back as new messages | ✅ |
| Watchdog | `agent.session_stall_timeout: 300` — notify-only | ✅ |
| Iteration bound | `agent.max_turns: 500` | ✅ |
| Standing goals | `goals.max_turns: 20` before auto-pause | ✅ |

**What does not exist:** a durable, queryable, resumable *workflow state machine* with typed states
and human-approval gates. ⛔ Hermes has sessions and cron jobs; it does not have `runs` with
`AWAITING_SUBREDDIT_REVIEW`. ◐ **Decisive inference**: our existing `runs`/`jobs` state machine
([04 §1–2](04-system-design.md)) is not redundant under Hermes and must be kept. The review gates —
the defining architectural constraint of this product ([01 §3](01-product-vision.md)) — have no
Hermes equivalent.

---

## 21. Docker Deployment ✅ / ⛔

- `docker-compose.yml` and a `docker/` directory exist in the repository. ✅ S2
- The **terminal backend** supports Docker with extensive hardening ✅:
  ```yaml
  terminal:
    backend: docker
    docker_image: "nikolaik/python-nodejs:python3.11-nodejs20"
    docker_network: true            # false = air-gap (--network=none)
    docker_persist_across_processes: true
    container_cpu: 1
    container_memory: 5120          # MB
    container_disk: 51200           # MB
  ```
  Hardening applied to every container: `--cap-drop ALL`, `--security-opt no-new-privileges`,
  `--pids-limit 256`, sized tmpfs for `/tmp`, `/var/tmp`, `/run`. Containers are tagged
  `hermes-agent=1`, `hermes-task-id=<id>`, `hermes-profile=<profile>`.
- The official Docker image sets `HERMES_WRITE_SAFE_ROOT=/opt/data`. ✅
- **A documented `docker compose up` deployment walkthrough was not found on the docs site.** ⛔
  Treat the compose file as the reference and validate it in Phase H1.

---

## 22. VPS Deployment ✅

- Marketing copy: *"Deployable on $5 VPS or GPU clusters."* ✅
- Concretely supported: `hermes gateway install` generates a **systemd user service**;
  `sudo hermes gateway install --system` generates a **boot-time system service**. ✅
- `hermes serve` starts *"the Hermes backend server — the JSON-RPC/WebSocket gateway"* for remote
  clients. ✅
- The installation page does **not** cover VPS specifics, resource sizing, or reverse proxying. ⛔

---

## 23. Cloud Deployment ✅

Seven execution backends, each with a stated isolation level:

| Backend | Where commands run | Isolation |
|---|---|---|
| `local` | The host | None |
| `docker` | Persistent container | Full (namespaces, cap-drop) |
| `ssh` | Remote server | Network boundary |
| `modal` | Modal cloud sandbox | Full cloud VM |
| `daytona` | Daytona workspace | Full cloud container |
| `vercel_sandbox` | Vercel microVM | Full cloud microVM |
| `singularity` | Singularity/Apptainer | Namespaces |

Modal and Daytona support hibernate/resume (`container_persistent: true`) — the docs claim
environments *"hibernate when idle and wake on demand, costing nearly nothing between sessions."* ✅

**Remote state sync** ✅: for SSH/Modal/Daytona, Hermes pushes `~/.hermes/` into the sandbox and syncs
changed files back on teardown by content hash, retrying up to 3 times, refusing archives >2 GiB.
Docker and Singularity use bind mounts instead.

---

## 24. Security ✅

Eight documented layers. The ones that matter to this project:

| Layer | Mechanism |
|---|---|
| Command approval | `approvals.mode: smart \| manual \| off`. `smart` uses an auxiliary LLM to triage; low risk auto-approves, dangerous auto-denies, uncertain escalates |
| Hardline blocklist | `rm -rf /`, fork bombs, `mkfs.*` on mounted devices, `dd if=/dev/zero of=/dev/sd*` — **blocked regardless of approval mode or YOLO** |
| Custom deny | `approvals.deny` fnmatch globs, applied before YOLO |
| Write guards | Always-blocked: `~/.ssh/`, `~/.aws/`, `/etc/sudoers`, `auth.json`, `.env`, `mcp-tokens/`, project `.env*` |
| Write sandbox | `HERMES_WRITE_SAFE_ROOT` restricts writes to a prefix |
| Env stripping | `execute_code` blocks vars containing `KEY, TOKEN, SECRET, PASSWORD, CREDENTIAL, PASSWD, AUTH`; Docker/Modal terminals get **no host env by default** |
| Injection scanning | Context files and memory entries scanned before entering the system prompt |
| Pre-exec scanning | *"Tirith"* detects homograph URL spoofing, pipe-to-interpreter, terminal injection |
| Skill scanning | Hub installs scanned for *"data exfiltration, prompt injection, destructive commands, supply-chain signals"*; `--force` cannot override a **dangerous** verdict |
| Supply chain | Advisory scanner for known-compromised Python packages in the venv; `security.allow_lazy_installs: false` |

**Stated threat-model limits, verbatim — quoted because they are unusually honest and we must not
over-claim on top of them:**

> "Deny rules are a guardrail against an honest-but-wrong agent … not a sandbox against a
> deliberately adversarial process."
>
> "The denylist reduces accidental damage and gives models a clear stop signal; it does not sandbox a
> hostile or compromised agent."
>
> `allow_private_urls: true` is "a deliberate trust boundary — only enable it on machines where the
> agent running arbitrary prompt-injected URLs against the local network is an acceptable risk."

**Reddit-content-specific risk, ours to own:** Reddit post bodies are attacker-controlled text. If a
Hermes agent ever reads raw Reddit content into its context with `terminal` enabled, prompt injection
becomes a remote-code-execution path. [21 §11](21-hermes-architecture.md) addresses this by denying
the agent tier the terminal toolset outright.

---

## 25. Performance ✅ / ⛔

Documented knobs:

```yaml
agent:
  max_turns: 500
  api_max_retries: 3
  session_stall_timeout: 300
compression:
  enabled: true
  threshold: 0.50          # compress at 50% of context limit
  target_ratio: 0.20
  protect_last_n: 20
  protect_first_n: 3
  in_place: true
tool_output:
  max_bytes: 50000
  max_lines: 2000
  max_line_length: 2000
file_read_max_chars: 100000
```

`execute_code` limits ✅: **300 s timeout, 50 KB stdout, 50 tool calls per execution.**

Gateway ✅: LRU agent cache, **128 entries, 3600 s idle TTL**, keyed by `session_key`; `move_to_end()`
on reuse *"preserving prompt cache state"*; expiry watcher every 5 minutes.

Timeouts ✅: `HERMES_STREAM_READ_TIMEOUT=120` (auto-raised to 1800 for local endpoints),
`HERMES_STREAM_STALE_TIMEOUT=180` (900 local), `HERMES_API_TIMEOUT=1800`,
`HERMES_API_CALL_STALE_TIMEOUT=90`.

**No published latency or throughput benchmarks.** ⛔

---

## 26. Token Optimization — the section that decides the architecture

### 26.1 What Hermes does for you ✅

| Mechanism | Effect |
|---|---|
| **Tiered system prompt** | *"assembles the ordered system-prompt tiers (**stable → context → volatile**): identity/tool guidance/skills, context files, then memory/profile/timestamp blocks"* |
| **Prompt stability** | *"System prompt doesn't change mid-conversation"* |
| **Progressive skill disclosure** | Level 0 metadata only (~3k), bodies on demand |
| **Progressive subdirectory discovery** | Nested `AGENTS.md` appended to *tool results*, explicitly for *"prompt cache preservation"* |
| **Gateway agent LRU** | Reuse *"preserving prompt cache state"* |
| **`execute_code`** | *"Only the script's `print()` output is returned to the LLM; intermediate tool results never enter the context window"* |
| **Delegation** | *"Only the final summary enters the parent's context, keeping token usage efficient"* |
| **Compression** | Summarise history at 50% of the context limit |
| **`session_search`** | FTS5 recall at **zero LLM cost** |
| **`hermes send`** | Messaging at **zero LLM cost** |

### 26.2 What Hermes does *not* do for our provider ✅

```yaml
prompt_caching:
  cache_ttl: "1h"     # "5m" or "1h" (Anthropic-supported tiers)
```

> "**Auto-enabled** for Claude on native Anthropic, OpenRouter, and Nous Portal."
> "Built-in cross-session **1-hour prefix cache for Claude**."

**Hermes' explicit prompt-cache machinery is Anthropic-shaped** — `cache_control` breakpoints with
Anthropic's TTL tiers. DeepSeek has no such mechanism; its caching is *implicit 64-token-chunk prefix
matching* ([02 §6.3b](02-research-findings.md)). ◐ **Inferred, high confidence**: on DeepSeek, Hermes
neither helps nor hinders caching directly — a hit depends entirely on whether the request prefix is
byte-identical to a previous one.

### 26.3 The four documented prefix invalidators

| Invalidator | Evidence | Our control |
|---|---|---|
| **Timestamp in the volatile tier** | Architecture doc: the tier order ends *"memory/profile/**timestamp** blocks"* | None. The stable+context tiers before it can still cache; everything from the timestamp onward cannot |
| **Growing message array** | Every tool-calling turn appends assistant + tool messages | Bound `max_turns`; prefer `execute_code`; keep tasks single-turn |
| **Micro-compaction** | `docs/micro-compaction.md`: *"A micro-compaction pass rewrites already-sent history"*, invalidating *"cached prefix tokens every turn instead of once per batch operation"*; *"can plausibly cost more than the stall it removes"* | **Off by default. Must stay off.** |
| **Mid-session model switch** | Tips: *"Avoid model switches mid-session — they reset the cache"* | Pin `cron.model` and the gateway model |

Hermes' own guidance, verbatim: *"Most LLM providers cache the conversation prefix (system prompt +
history). If you keep your system prompt stable (same context files, same memory), subsequent
messages in a session get cache hits that are significantly cheaper."*

### 26.4 The verdict that shapes everything downstream

> **A Hermes agent turn cannot be made byte-stable across thousands of independent items, and its
> per-item token cost is not bounded by construction.**

This follows from three verified facts: the volatile tier contains a timestamp; each tool-calling
turn appends to the message array; and `max_turns` defaults to 500. Our enrichment path needs the
opposite properties — a frozen 3,500-token prefix, one round trip per batch of 8, and a hard call
ceiling ([06b §3](06b-deepseek-optimization.md), [06a §5](06a-ai-service-layer.md)).

**→ Therefore the high-volume enrichment path stays inside `AIService` and never enters a Hermes
agent loop.** This is [21 §3, AD-21](21-hermes-architecture.md), and it is the load-bearing decision
of the entire redesign.

---

## 27. DeepSeek Integration ✅ S3

Verbatim from the DeepSeek documentation:

```
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
```

Then `hermes setup` → Quick Setup → provider **DeepSeek** → API key from
`https://platform.deepseek.com/api_keys` → Base URL `https://api.deepseek.com` → model
**`deepseek-v4-pro`**.

Equivalent declarative configuration ◐ (composed from the verified `config.yaml` schema in §"Model &
Provider Selection"):

```yaml
model:
  default: deepseek-v4-pro          # S3's recommendation
  provider: deepseek
  base_url: "https://api.deepseek.com"
```
```bash
# ~/.hermes/.env
DEEPSEEK_API_KEY=sk-...
```

**Two notes we must carry forward.**

1. **S3 recommends `deepseek-v4-pro`; our pipeline is standardised on `deepseek-v4-flash`**
   ([02 §6.2](02-research-findings.md), D30). Pro is the more capable and more expensive sibling.
   [24 §6](24-cost-optimization.md) pins the agent tier to **v4-flash** with v4-pro as an
   evidence-gated escalation, consistent with D30 rather than with S3's default.
2. **The current live deployment runs OpenRouter, not DeepSeek direct**
   ([PHASE-01-STATUS](PHASE-01-STATUS.md)). On OpenRouter, cached input is `$0.028/M` — a **5×**
   differential, not 50× — and `cached_tokens` telemetry is absent. Every cost figure in
   [24](24-cost-optimization.md) states which provider path it assumes.

---

## 28. Multi-Agent Best Practices ✅

Distilled from S1 (*Tips*, *Delegation*, *Code Execution*):

1. **Prefer `execute_code` to `delegate_task`** when the workflow shape is known. Delegation is
   *"Higher (full LLM loop)"*; `execute_code` is one turn with intermediate results excluded from
   context.
2. **Pass everything a subagent needs explicitly** — *"Subagents start with a completely fresh
   conversation."*
3. **Keep depth at 1** unless a tree is genuinely required; the docs spell out the 27-agent
   combinatorial blow-up at depth 3.
4. **Use delegation for parallel *research*** — the documented example is *"Need to research three
   topics at once?"*
5. **Bound iterations** — `max_iterations` defaults to 50 per child.
6. **Batch terminal work into a script** — *"Instead of running terminal commands one at a time, ask
   the agent to write a script that does everything at once."*

---

## 29. Existing Community Patterns ✅ / ⛔

Verified ecosystem surface:

- **Skills Hub / agentskills.io**, plus `skills.sh` (Vercel's directory), `/.well-known/skills/index.json`
  endpoints, direct GitHub taps, direct URLs, and community marketplaces (ClawHub, LobeHub, browse.sh).
- **Trust tiers**: `builtin` → `official` → `trusted` (`openai/skills`, `anthropics/skills`,
  `huggingface/skills`, `NVIDIA/skills`) → `community`.
- **Custom taps**: `hermes skills tap add my-org/hermes-skills`, then
  `hermes skills install my-org/hermes-skills/deploy-runbook`.
- **OpenClaw migration**: `hermes claw migrate` imports settings, memories, skills, API keys,
  allowlists, messaging configs, TTS assets, and `AGENTS.md`.

**No published Reddit-monitoring, lead-generation, or scraping-pipeline reference architecture was
found.** ⛔ There is no community pattern to copy for this use case; §21–24 of the architecture
document are original design.

---

## 30. Known Limitations

Documented ✅:

- Native Windows needs bundled MinGit; antivirus false-positives on `uv.exe` require whitelisting
  `%LOCALAPPDATA%\hermes\bin`.
- Android/Termux uses curated `.[termux]` extras; full `.[all]` is incompatible.
- Manual venvs must live outside the source tree *"to prevent accidental deletion by agent commands."*
- The compression model *"**must** have a context window at least as large as your main agent
  model's."*
- Micro-compaction can cost more than it saves on deep-cache-discount providers.
- `--force` on a skill install cannot override a **dangerous** security verdict.

Structural, inferred ◐ — the ones that shape our design:

| # | Limitation | Consequence |
|---|---|---|
| L1 | **No durable workflow state machine with human gates** | Keep `runs`/`jobs`; Hermes cannot own the pipeline |
| L2 | **No structured, versioned, evidence-carrying knowledge store** | Keep the BKB in our schema; expose it as a tool |
| L3 | **Memory is 1,300 tokens total** | Cannot hold business knowledge; use for operator preferences only |
| L4 | **No agent-to-agent messaging; profiles fully isolated** | Any shared state goes through our database via HTTP |
| L5 | **Per-turn token cost is unbounded by construction** | Never put the high-volume path in an agent loop |
| L6 | **Prefix stability not guaranteeable across items** | The 50× (or 5×) cache discount is unavailable in-agent |
| L7 | **Tool/MCP schema token cost undocumented** | Must be measured; prune toolsets aggressively |
| L8 | **Agent reads untrusted text** | Reddit bodies are attacker-controlled; deny `terminal` in the agent tier |

---

## 31. Recommended Folder Structure ✅

Verified canonical layout of a Hermes home:

```
~/.hermes/                       # or $HERMES_HOME, or per-profile ~/.hermes-<name>/
├── config.yaml                  # models, terminal, compression, mcp_servers, skills, telegram…
├── .env                         # secrets ONLY
├── auth.json                    # OAuth credentials
├── SOUL.md                      # identity — "system prompt slot #1"
├── memories/
│   ├── MEMORY.md                # ≤2,200 chars
│   └── USER.md                  # ≤1,375 chars
├── skills/
│   ├── .bundled_manifest
│   └── <category>/<skill>/SKILL.md + references/ templates/ scripts/ examples/ assets/
├── skill-bundles/<slug>.yaml
├── plugins/<name>/{plugin.yaml,__init__.py,schemas.py,tools.py}
├── hooks/<name>/{HOOK.yaml,handler.py}
├── cron/
│   ├── jobs.json
│   ├── executions.db
│   ├── .tick.lock
│   └── output/{job_id}/{timestamp}.md
├── pairing/                     # chmod 0600
├── pending/skills/              # staged writes when write_approval: true
├── sessions/
├── state.db                     # sessions + FTS5 + delivery ledger
└── logs/
```

Our project-specific layout is specified in [21 §12](21-hermes-architecture.md).

---

## 32. Existing Built-in Skills ⛔ / ✅

**No exhaustive list of bundled skills is published.** ⛔ Named in passing ✅: `duckduckgo-search`
(uses `fallback_for_toolsets: [web]`), `google-workspace`, `blogwatcher`, `maps`, `gif-search`,
`github-pr-workflow`, `github-code-review`, `test-driven-development`, `plan`, `skill-creator`,
`1password` (under `official/security/`).

Enumerate the real list with `hermes skills browse --source official` during Phase H1.

---

## 33. Skills Hub ✅

Six install sources: `official`, `skills-sh`, `well-known`, `github`, `url`, and community
marketplaces. Commands:

```
hermes skills browse [--source official]
hermes skills search kubernetes
hermes skills inspect openai/skills/k8s
hermes skills install openai/skills/k8s
hermes skills check | update | audit | uninstall <name>
hermes skills reset <name> [--restore]
hermes skills tap add | list | remove <owner/repo>
```

All hub installs pass a security scanner. Bundled skills sync on `hermes update`, tracked by
`~/.hermes/skills/.bundled_manifest`: **unchanged skills receive upstream updates automatically;
user-modified skills are flagged and skipped forever.**

Opt-out: `--no-skills` at install, `hermes profile create <p> --no-skills`, or
`hermes skills opt-out [--remove]`. Note *"`hermes skills opt-out` only stops future seeding — it
never deletes anything already on disk."*

◐ **Design consequence**: bundled skills are a *permanent Level-0 token tax* for capabilities we do
not need. [24 §3](24-cost-optimization.md) makes `--no-skills` profile creation a hard requirement.

---

## 34. Memory Lifecycle ✅

1. **Write** — the `memory` tool (`add`/`replace`/`remove`), optionally gated by
   `memory.write_approval: true` with staging reviewable at `/memory pending`.
2. **Security scan** — injection/exfiltration patterns rejected; exact duplicates rejected.
3. **Bound** — hard character limits; overflow returns *"Consolidate now."*
4. **Freeze** — *"injected into the system prompt as a frozen snapshot at session start"*;
   *"changes made during a session don't appear in the system prompt until the next session starts."*
5. **Background review** — a self-improvement pass runs after turns and may update memory
   (`display.memory_notifications`).
6. **Prune** — `/journey`, `hermes journey delete|edit <node>`. Skills are archived; memory removed.

---

## 35. State Persistence ✅

| State | Where |
|---|---|
| Sessions, transcripts, FTS5 index, delivery ledger | `~/.hermes/state.db` (SQLite) |
| Session metadata | `sessions.json` |
| Cron jobs / history | `cron/jobs.json`, `cron/executions.db` |
| Memory | `memories/MEMORY.md`, `memories/USER.md` |
| Skills | `skills/` on disk |
| Credentials | `.env`, `auth.json` |
| Pairing | `pairing/` (0600) |

Session IDs are `YYYYMMDD_HHMMSS_<8hex>`; session keys are
`agent:main:{platform}:{chat_type}[:{chat_id}][:{thread_id}][:{participant_id}]`. Sessions have
lineage (parent/child across compressions), per-platform isolation, and atomic writes with contention
handling. ✅

---

## 36. Logging ✅

`hermes logs [-f|--follow] [--session <id>]`; logs at `~/.hermes/logs/` (error and gateway logs).
`hermes dump` produces a *"copy-pasteable setup summary for support/debugging"*. Tool progress can be
routed to an audit log rather than chat:

```yaml
display:
  tool_progress: all      # off | new | all | verbose | log
  tool_progress_grouping: accumulate
```

**No structured/JSON log format and no correlation-ID convention is documented.** ⛔ Our
`run_id`/`job_id`/`project_id` correlation ([03 §7](03-architecture.md)) does not extend into Hermes
automatically; [21 §10](21-hermes-architecture.md) carries it across the boundary explicitly.

---

## 37. Error Recovery ✅

| Failure | Recovery |
|---|---|
| Gateway crash mid-reply | Durable delivery ledger redelivers with a *"♻️ Recovered reply"* prefix |
| Gateway restart | `resume_pending` sessions keep their `session_id`; `.clean_shutdown` marker drives `suspend_recently_active()` |
| Restart loop | Sessions active across 3+ consecutive restarts auto-suspend |
| Cron job abandoned | Marked `unknown` **only** when PID + process-start fingerprint prove the owner is gone |
| Overlapping cron ticks | `.tick.lock` file lock |
| Provider failure | Fallback provider chains; credential pools rotate keys on failure |
| Platform adapter failure | Circuit-breaker alerts |
| Hook error | *"All four systems are non-blocking — errors in any hook are caught and logged, never crashing the agent"* |
| Stalled session | `agent.session_stall_timeout` — **notify-only**, does not kill |

---

## 38. Retry Strategy ✅ / ⛔

- `agent.api_max_retries: 3` — *"Retries before fallback engages."*
- **Fallback providers**: automatic failover on primary model errors, with independent fallback for
  auxiliary tasks; `auxiliary.compression.fallback_chain` shown with a `provider`/`model` list.
- **Credential pools**: *"Distribution of API calls across multiple keys for the same provider"* with
  automatic rotation on failures.
- Stream/stale timeouts via the `HERMES_*_TIMEOUT` env vars (§25).
- **Backoff curve, jitter, and per-error-class retryability are not documented.** ⛔

◐ Our `AIService` retry policy ([06a §8.3](06a-ai-service-layer.md)) is more precisely specified than
Hermes' — 401/402 as non-retryable product states, concurrency halving on 429/503. **This is a second
reason the enrichment path stays in `AIService`**: Hermes' retry semantics are neither documented nor
ours to own.

---

## 39. Monitoring ✅ / ⛔

Available:

- `SessionEntry` tracks `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`,
  `total_tokens`, `estimated_cost_usd`. ✅
- `hermes -z --usage-file <path>` writes a machine-readable per-run usage report. ✅
- `hermes doctor` diagnoses config/dependency issues; `hermes dump` summarises setup. ✅
- **Outbound webhooks** push HMAC-SHA256-signed events to an HTTP endpoint, fire-and-forget off the
  hot path, with `delivery_id` + `timestamp` inside the signed body giving replay protection. ✅
- Gateway circuit-breaker alerts on repeated adapter failure. ✅

Missing: **no metrics endpoint, no Prometheus exporter, no health endpoint.** ⛔

◐ **Design consequence**: the outbound webhook is the correct integration seam. Hermes pushes signed
lifecycle events to our Flask app, which records them alongside `ai_calls` — so agent-tier spend
appears on the same `/health/ai` page as pipeline spend rather than in a second, unread place.

---

## 40. Production Readiness — assessment

| Dimension | State | Note |
|---|---|---|
| Licence | ✅ MIT | No commercial dependency to lose — matches D1's reasoning |
| Maturity | ⚠️ **v0.20.0** | Pre-1.0. Expect breaking changes; pin the version |
| Security posture | ✅ Strong, and honestly scoped | Eight layers, with stated non-guarantees |
| Service management | ✅ systemd / launchd | Boot-time supported |
| Crash recovery | ✅ Real | Delivery ledger, session resume, cron fingerprinting |
| Secrets | ✅ Reasonable | `.env`-only, redaction, env stripping, MCP filtering |
| Observability | ⚠️ Partial | Usage reports and webhooks; no metrics/health endpoint |
| Cost control | ⛔ **Absent** | **No per-run or per-day spend cap exists in Hermes** |
| Determinism | ⛔ By design | An agent loop is not reproducible |
| Multi-tenancy | ✅ Profiles + routing | Full isolation |
| Upgrade path | ⚠️ `hermes update` pulls latest | Auto-restarts gateways; pin and test |

**The cost-control gap is the single most serious production finding.** Our platform enforces four
independent ceilings checked *before* every call ([06d §4](06d-ai-budget-and-scale.md)). Hermes has
no equivalent — an agent in a tool-calling loop can spend until `max_turns: 500` is reached.
[24 §7](24-cost-optimization.md) specifies the external governor that closes this gap, and
[21 §9](21-hermes-architecture.md) makes it a hard architectural component rather than an operational
habit.

---

## 41. Evidence summary

| Class | Topics |
|---|---|
| ✅ **Verified from source** | 1, 2, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 24, 27, 28, 31, 33, 34, 35, 37 |
| ✅ + ◐ **Verified with an explicit inference** | 3, 8, 20, 22, 23, 25, 26, 29, 30, 36, 38, 39, 40 |
| ⛔ **Gaps found and left as gaps** | Tool/MCP schema token cost; Docker-compose walkthrough; VPS sizing; latency benchmarks; retry backoff curve; metrics endpoint; exhaustive built-in skill list; a `/docs/user-guide/features/prompt-caching` page (feature confirmed via the features index and `config.yaml` only) |

**Eight of the forty topics carry a material gap.** Each is closed by a *measurement task* in
[25 — Phase H1](25-hermes-roadmap.md) rather than by an assumption here.
