<p align="center">
  <h1 align="center">⚙️ Agent Harness Engineer Skill</h1>
  <p align="center">
    <strong>Production-grade AI Agent Construction Blueprint</strong>
    <br />
    A <a href="https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/skills">Skill</a> that guides AI coding tools to build enterprise-ready Agent systems — not just demos.
  </p>
</p>

<p align="center">
  <a href="https://github.com/nicepkg/agent-harness-engineer/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="License" /></a>
  <a href="https://github.com/nicepkg/agent-harness-engineer/stargazers"><img src="https://img.shields.io/github/stars/nicepkg/agent-harness-engineer?style=flat&color=yellow" alt="Stars" /></a>
  <a href="#"><img src="https://img.shields.io/badge/version-v4.0.0-brightgreen.svg" alt="Version" /></a>
  <a href="https://agentskills.io"><img src="https://img.shields.io/badge/Agent%20Skills-open%20standard-blueviolet.svg" alt="Agent Skills" /></a>
  <a href="README_ZH.md"><img src="https://img.shields.io/badge/中文文档-简体中文-red.svg" alt="Chinese Doc" /></a>
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/changelog-v4-orange.svg" alt="Changelog" /></a>
</p>

---

## What's New in v4

v4 closes four structural gaps and reverses two outdated paradigms:

| Area | v4 Adds |
|------|---------|
| 🧪 **Evaluation** | New **Phase 8**: 3-layer metrics, trace assertions, judge calibration (85% gate), `pass^k`, CI regression gates |
| ✅ **Verification Loop** | `CONTINUE-SITE-8` (verification failure) + Verifier contract — wrap probabilistic intelligence in deterministic checks |
| 💰 **Budget Control** | `Budget` / `BudgetPolicy`, 4-step degradation chain, `ModelRouter` (cheap vs. strong per step) |
| 🔁 **Long-Running** | Handoff files, `feature_list.json`, Initializer/Coding dual-role, 5-step session ritual |
| 🔄 **Compression Fixed** | **Mask-first** pipeline, trigger threshold 85% → **60-70%**, compaction ledger |
| 🔧 **Tools Reversed** | From "more tools = better" to **few, strong tools + code execution** (−98.7% tokens in the canonical case) |
| 🩺 **Quality Observability** | 8 quality metrics, production sampling & drift alerts, redaction whitelist |

See [CHANGELOG.md](CHANGELOG.md) for the full list including **breaking changes** (`13` file renamed, `project-scaffold` → `examples/`, MCP transport now **Streamable HTTP**).

---

## Why Agent Harness Engineer?

Most "Build an Agent" tutorials give you a 50-line Python script that calls an LLM in a loop. That's a demo, not a production system.

**Agent Harness Engineer** is different. It's a comprehensive **8-phase construction blueprint** that AI coding tools follow to generate structurally complete, secure, extensible Agent systems — complete with permission models, context compression pipelines, multi-agent coordination, sandbox isolation, deterministic verification, budget control, **and an evaluation suite that proves the thing actually works**.

> *"Information that the Agent cannot access in its context does not exist."* — Harness Engineering Principle
>
> *"A model that can't prove its reliability can't be put in production."* — v4 Principle

---

## Quick Start

This is a **[Agent Skills](https://agentskills.io) open standard Skill** (governed by the Linux Foundation's Agentic AI Foundation) consumed by AI coding assistants — Claude Code, Codex, Cursor, Gemini CLI, GitHub Copilot, VS Code, Goose, OpenCode and ~40 others.

### Installation

Copy (or symlink) this repository into your tool's skills directory:

| Tool | Path |
|------|------|
| Claude Code | `.claude/skills/agent-harness-engineer/` |
| Codex / OpenAI | `.agents/skills/agent-harness-engineer/` |
| Cursor | `.cursor/skills/agent-harness-engineer/` |
| Any AGENTS.md-aware tool | add an `AGENTS.md` entry pointing at this directory |

```bash
git clone https://github.com/nicepkg/agent-harness-engineer.git
```

Then simply ask your AI coding tool:

```
"Build me an Agent"
```

The AI will load this Skill and guide you through a structured **8-phase** build process — from scaffolding to production deployment **to proving it works**.

> ⚠️ **Skill supply-chain safety**: Skills are executable content disguised as documentation — `references/` may contain prompt injection and `scripts/` run with your host credentials. **Possessing a Skill does not grant it tool authorization.** Pin versions, review scripts before enabling, and never pre-authorize shell access for a freshly cloned repository.

When triggered, the Skill will:
1. Confirm your requirements (tech stack, LLM provider, scale, use case, **evaluation needs**, **cost budget**, **long-running needs**)
2. Load only the references it needs (see the routing table in `SKILL.md` — it practices what it preaches)
3. Execute each phase sequentially with checklist verification
4. Generate a **custom-designed** Agent project — see the anti-copy rule below

---

## 🚫 The Anti-Copy Rule (Core Differentiator)

> **AI coding tools must design and write code, not copy it.**

Every method body in `references/`, `templates/` and `examples/` is a **skeleton**: real signatures, type annotations, and a `raise NotImplementedError("AI: <build prompt>")`. Nothing here is a drop-in implementation.

**Why this matters:** when references contain complete working code, the AI copies it — and you always get the same minimal implementation regardless of your requirements, scale, or tech stack. Worse, those implementations often skip safety constraints (e.g. a `read_file` with no path allowlist), which then gets learned as the correct pattern.

---

## Core Framework: Harness Engineering

<p align="center">
  <b>Three Pillars of Production Agent Systems</b>
</p>

| Pillar | Principle | Implementation |
|--------|-----------|----------------|
| **Context Engineering** | Information accessibility is everything | Mask-first 4-level compression, tool search lazy loading, external scratchpad memory |
| **Architectural Constraints** | Mechanical enforcement beats suggestions | 5 permission modes × 7 rule hierarchies, schema validation, sandbox isolation, budget ceilings |
| **Entropy Management** | Code degrades without regular maintenance | Documentation audits, constraint violation scanning, coverage gates, eval regression suite |

---

## 8-Phase Construction Blueprint

```
Phase 1  ●──○ Project Init       ▸ Scaffolding, config, AGENTS.md, skills loader
Phase 2  ●──○ LLM Abstraction    ▸ Provider-agnostic client + ModelRouter
Phase 3  ●──○ Tool System        ▸ Few strong tools, code execution, tool search
Phase 4  ●──○ Agent Core Loop    ▸ 8 continue-sites, Verifier contract, streaming bus
Phase 5  ●──○ Context Management ▸ Mask→Snip→Collapse→Autocompact + ledger, WAL
Phase 6  ●──○ Permissions        ▸ 6-layer defense, sandbox, audit, budget control
Phase 7  ●──○ Production         ▸ Deterministic gates, monitoring, structured logging
Phase 8  ●──○ Evaluation         ▸ 3-layer metrics, judge calibration, CI regression gate
```

Each phase includes: **Theory → Practice Steps → Checklist → Common Pitfalls**

---

## Architecture in 30 Seconds

```
┌─────────────────────────────────────────────────────────┐
│                      HARNESS                            │
│                (Stateless Orchestrator)                  │
│                                                         │
│   while (running) {                                     │
│     step = yield from Session.next()                    │
│     result = Sandbox.execute(step)                      │
│     Session.commit(result)                              │
│   }                                                     │
└──────────┬──────────────────────────┬───────────────────┘
           │                          │
    ┌──────▼──────┐           ┌──────▼──────┐
    │   SESSION   │           │   SANDBOX   │
    │ Append-only │           │  Isolated   │
    │  Event Log  │           │  Execution  │
    │ Immutable & │           │  Env (fs,   │
    │ Replayable  │           │  net, proc) │
    └─────────────┘           └─────────────┘
```

**Session** — Immutable append-only event log (like database WAL). The single source of truth.  
**Harness** — Stateless orchestration loop. Crash-tolerant, can restart from any point.  
**Sandbox** — Isolated execution environment. Blast radius containment.

---

## Features

<table>
<tr>
<td width="50%">

### 🔒 Production Security
- **6-layer defense-in-depth** security model
- Permission modes: `allow` / `deny` / `ask`
- Pre/post tool-use hooks for auditing
- Sandbox isolation (filesystem, network, process)
- Hardcoded deny rules for dangerous commands

</td>
<td width="50%">

### 🧠 Advanced Context Management
- **Mask-first 4-level compression pipeline**
  - Mask → Snip → Collapse → Autocompact *(mask before summarizing: −52% cost, +2.6% solve rate)*
- Trigger threshold **60–70%**, not 85%
- Compaction ledger — know afterwards what got dropped
- External scratchpad memory survives compaction losslessly
- `tool search` lazy loading to conserve context window

</td>
</tr>
<tr>
<td width="50%">

### 🔧 Multi-Provider LLM Support
- Provider-agnostic `LLMClient` interface
- Anthropic, OpenAI, Azure, Local (Ollama/vLLM)
- Factory pattern for zero-code switching
- Streaming (async generator) architecture

</td>
<td width="50%">

### 🤖 Multi-Agent, MCP & Protocols
- Coordinator / Swarm / Manager-Worker / Generator-Critic / Debate
- **Independent Evaluator** agent & adversarial verification
- MCP over **Streamable HTTP** (remote default) or stdio (local default)
- A2A for agent↔agent, AG-UI for agent↔frontend
- Sub-agent context isolation with summary-only returns

</td>
</tr>
</table>

---

## templates/ vs examples/ — Know the Difference

> **Neither is meant to be copied.** Both are skeletons: real signatures, `raise NotImplementedError("AI: …")`, and a build prompt. See the [anti-copy rule](#-the-anti-copy-rule-core-differentiator).

| Directory | What it is | How to use it |
|-----------|-----------|---------------|
| `templates/minimal/`<br>`templates/professional/`<br>`templates/enterprise/` | **Scale scaffolds** — a starting skeleton sized to Minimal / Professional / Enterprise | Start here. Pick the tier that matches your requirements, then let the AI design each module. |
| `examples/python/`<br>`examples/nodejs/` | **Teaching reference** — a skeletonized map of what the *complete* architecture looks like across every module | Read it to understand how the pieces fit together. Do **not** use as a scaffold. *(In v3 this was `templates/project-scaffold/` and contained full implementations — that directory has been skeletonized and moved.)* |

```
templates/                    Scale scaffolds (pick one tier)
├── minimal/                  ~300-500 lines, almost no deps
├── professional/             ~2-4k lines, Docker sandbox, tests, structured logs
└── enterprise/               ~6-10k lines, tracing, microVM, multi-agent

examples/                     Teaching reference — how the modules connect
├── python/
│   ├── src/agent/            core loop, session, context, memory
│   ├── src/llm/              client abstraction, factory, providers, router
│   ├── src/tools/            registry, file tools, network tools
│   ├── src/permissions/      models, hooks, sandbox
│   ├── src/utils/            logging, errors
│   └── config/ skills/ tests/
└── nodejs/                   mirror of the Python layout
```

### Reference Stack (recommendations, not requirements)
- **Python**: `anthropic` · `openai` · `httpx` · `pydantic` · `pyyaml` · `pytest` · `structlog` · `docker` · `promptfoo`/`deepeval`
- **Node.js**: `@anthropic-ai/sdk` · `openai` · `axios` · `js-yaml` · `zod` · `vitest` · `pino` · `dockerode`

Full three-tier recommendations live in [`references/11-technology-stack.md`](references/11-technology-stack.md), including evaluation, tracing, model routing and sandbox dimensions.

---

## 11 Design Philosophies

1. **Async Generator Streaming** — yield intermediate events, don't just return results
2. **Continue-Sites for Recovery** — `while(true)` + 8 recovery points, incl. verification failure
3. **Compile-Time Feature Gating** — dead code elimination at build time
4. **Cache-Prefix Stability** — built-in tools as stable prefix, `tool search` doesn't invalidate cache
5. **Defense-in-Depth** — 6-layer superposition makes bypass probability decay exponentially
6. **Data-Driven Extensibility** — `settings.json` + `agents/*.md` + `skills/*.md` + hooks
7. **Context as Scarce Resource** — mask first, `tool search`, external scratchpad, 4-level compression
8. **Hierarchical Config Override** — CLI > Flag > Policy > Managed > Local > Project > User
9. **Isolated Sub-Agent Contexts** — blank message list, summary-only return
10. **Reversibility-First** — Edit via string replacement, not file overwrite
11. **Few Tools Beat Many, and Code Execution Beats Tool Calls** — orchestrate in a sandbox script instead of paying N round-trips into the context window

---

## When to Use

This Skill auto-triggers on keywords like:

> "Build an agent" · "Create an AI assistant" · "Design an agent system" · "Agent optimization" · "Agent scaffolding" · "Agent project template" · "Agent framework" · "Multi-agent" · "Agent upgrade" · **"harness engineering" · "context engineering" · "agent evaluation / eval" · "long-running agent" · "cross-session handoff" · "build a skill" · "agent cost / budget"**

### Use Cases

| Scale | Description | Example |
|-------|-------------|---------|
| **Small** | Personal assistant | Coding helper, note organizer |
| **Medium** | Team tooling | Code review bot, CI/CD assistant |
| **Large** | Enterprise platform | Customer support swarm, ops automation fleet |

---

## Repository Layout

```
SKILL.md          Hub: routing table, requirements checklist, design philosophies
AGENTS.md         Repo-level instructions for AI coding tools changing this repo
CHANGELOG.md      Version history incl. v4 breaking changes
references/       15 deep-dive documents (Phase 1-8 + core concepts + ops topics)
templates/        Scale scaffolds: minimal / professional / enterprise
examples/         Skeletonized teaching reference (do not copy)
evals/            Structured eval suite: scenarios / graders / baseline
```

> 15 reference documents is a lot of context — that's why `SKILL.md` ships a **routing table** telling the AI which 2–6 files to load for the job at hand. The Skill practices the progressive disclosure it teaches.

---

## Roadmap

- [x] 8-phase construction blueprint (v2 → v4)
- [x] Python & Node.js reference layouts
- [x] Multi-agent coordination patterns
- [x] MCP protocol integration → **Streamable HTTP**, A2A, AG-UI
- [x] 6-layer defense-in-depth security
- [x] 4-level context compression pipeline → **mask-first** (v4)
- [x] v4 Loop Engineering upgrade
- [x] **Evaluation suite & CI regression gates** (v4)
- [x] **Deterministic verification loop** (v4)
- [x] **Budget control & model routing** (v4)
- [x] **Long-running / cross-session handoff** (v4)
- [ ] Go language scaffold
- [ ] Visual architecture diagrams
- [ ] Real-world case studies

---

## Contributing

Contributions are welcome! Here's how you can help:

- Add scaffolds for new languages (Go, Rust, TypeScript-native)
- Improve reference documentation
- Add evaluation test cases
- Share real-world case studies of agents built with this Skill

Please read the [contributing guide](CONTRIBUTING.md) before submitting a PR.

---

## License

This project is licensed under the Apache License 2.0 — see [LICENSE](LICENSE) for details.

---

<p align="center">
  <sub>Built with ❤️ by the Agent Engineering Community</sub>
  <br />
  <sub>If this project helps you, please ⭐ star it on GitHub!</sub>
</p>
