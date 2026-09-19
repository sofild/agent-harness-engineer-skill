<p align="center">
  <h1 align="center">⚙️ Agent Harness Engineer</h1>
  <p align="center">
    <strong>生产级 AI Agent 系统构建蓝图</strong>
    <br />
    一个指导 AI 编程工具构建企业级 Agent 系统的 <a href="https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/skills">Skill</a>，告别玩具 Demo，生成生产就绪代码。
  </p>
</p>

<p align="center">
  <a href="https://github.com/nicepkg/agent-harness-engineer/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="License" /></a>
  <a href="https://github.com/nicepkg/agent-harness-engineer/stargazers"><img src="https://img.shields.io/github/stars/nicepkg/agent-harness-engineer?style=flat&color=yellow" alt="Stars" /></a>
  <a href="#"><img src="https://img.shields.io/badge/版本-v4.0.0-brightgreen.svg" alt="Version" /></a>
  <a href="https://agentskills.io"><img src="https://img.shields.io/badge/Agent%20Skills-开放标准-blueviolet.svg" alt="Agent Skills" /></a>
  <a href="README.md"><img src="https://img.shields.io/badge/English-README-blue.svg" alt="English Doc" /></a>
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/变更记录-v4-orange.svg" alt="Changelog" /></a>
</p>

---

## v4 更新了什么

v4 补齐了四个结构性缺口，并修正了两处方向反了的范式：

| 方向 | v4 新增/修正 |
|------|-------------|
| 🧪 **评测体系** | 新增 **第八阶段**：三层指标、轨迹断言、judge 校准（85% 门槛）、`pass^k`、CI 回归门禁 |
| ✅ **确定性验证回路** | `CONTINUE-SITE-8`（验证失败）+ Verifier 契约 —— 用确定性反馈包裹概率性智能 |
| 💰 **预算与成本控制** | `Budget` / `BudgetPolicy`、四级降级链、`ModelRouter`（按步骤路由强弱模型） |
| 🔁 **长时运行与跨会话** | handoff 文件、`feature_list.json`、Initializer/Coding 双角色、五步会话初始化仪式 |
| 🔄 **压缩管道修正** | 改为**遮蔽优先**，触发阈值 85% → **60-70%**，新增压缩台账 |
| 🔧 **工具范式反转** | 从"工具越多越强大"到**少而精 + 代码执行**（典型场景 −98.7% token） |
| 🩺 **质量可观测** | 8 个质量指标、生产采样与漂移告警、日志脱敏白名单 |

完整清单（含**破坏性变更**：`13` 文件更名、`project-scaffold` → `examples/`、MCP 远程改走 **Streamable HTTP**）见 [CHANGELOG.md](CHANGELOG.md)。

---

## 为什么需要 Agent Harness Engineer？

大多数"教你构建 Agent"的教程，只会给你一个 50 行的 Python 脚本，在循环里调用 LLM。那是 Demo，不是生产系统。

**Agent Harness Engineer** 完全不同。它是一套完整的 **8 阶段构建蓝图**，AI 编程工具会按照它逐步生成结构完整、安全可靠、可扩展的 Agent 系统 —— 包含权限模型、上下文压缩管道、多智能体协作、沙箱隔离、确定性验证、预算控制，**以及一套能证明它真的可用的评测体系**。

> *"Agent 在其上下文中无法访问的信息，就不存在。"* —— Harness 工程核心原则
>
> *"无法证明可靠性的模型，无法进入生产。"* —— v4 核心原则

---

## 快速开始

这是一个遵循 **[Agent Skills](https://agentskills.io) 开放标准**（由 Linux Foundation 旗下 Agentic AI Foundation 治理）的 Skill，可被 Claude Code、Codex、Cursor、Gemini CLI、GitHub Copilot、VS Code、Goose、OpenCode 等约 40 个工具使用。

### 安装

把本仓库复制（或软链）到对应工具的 skills 目录：

| 工具 | 路径 |
|------|------|
| Claude Code | `.claude/skills/agent-harness-engineer/` |
| Codex / OpenAI | `.agents/skills/agent-harness-engineer/` |
| Cursor | `.cursor/skills/agent-harness-engineer/` |
| 支持 AGENTS.md 的工具 | 在 `AGENTS.md` 中指向本目录 |

```bash
git clone https://github.com/nicepkg/agent-harness-engineer.git
```

然后对你的 AI 编程工具说：

```
"帮我构建一个 Agent"
```

AI 将加载此 Skill，按结构化的 **8 阶段**流程引导你完成从脚手架到生产部署**再到证明它好用**的全过程。

> ⚠️ **Skill 供应链安全提示**：Skill 是"伪装成文档的可执行内容" —— `references/` 可能包含 prompt injection，`scripts/` 以宿主凭据运行。**持有 Skill 不等于获得工具授权。** 请锁定版本、启用前审阅脚本、不要为新克隆的仓库预授权 Shell。

触发后，Skill 会：
1. 确认你的需求（技术栈、LLM 供应商、规模、用途、**评测要求**、**成本预算**、**是否长时运行**）
2. 只加载需要的 reference（`SKILL.md` 里有**加载路由表** —— 它自己就在实践渐进式披露）
3. 按阶段逐步执行，每阶段自动检查验收
4. 生成**为你的需求定制设计**的 Agent 项目 —— 见下方禁止复制规则

---

## 🚫 禁止复制规则（本项目最核心的差异点）

> **AI 编程工具必须自己设计并编写代码，不得直接复制。**

`references/`、`templates/`、`examples/` 中的每一个方法体都是**骨架**：真实签名、类型注解，加上一句 `raise NotImplementedError("AI: <构建提示>")`。这里没有可直接落地的实现。

**为什么重要**：一旦 reference 里有完整可运行代码，AI 就会复制它 —— 于是无论你的需求、规模、技术栈是什么，拿到的永远是同一份最小实现。更糟的是这些实现常常缺失安全约束（例如不带路径白名单的文件读取），会被 AI 当作正确范式学走。

---

## 核心框架：Harness Engineering

<p align="center">
  <b>生产级 Agent 系统的三大支柱</b>
</p>

| 支柱 | 原则 | 实现方式 |
|------|------|----------|
| **上下文工程**<br>Context Engineering | 信息可达性决定一切 | 遮蔽优先的四级压缩管道、tool search 延迟加载、外置 scratchpad 记忆 |
| **架构约束**<br>Architectural Constraints | 机械执行胜过人工建议 | 5 种权限模式 × 7 级规则层级、Schema 校验、沙箱隔离、预算天花板 |
| **熵管理**<br>Entropy Management | 代码不维护就会退化 | 文档一致性审计、约束违规扫描、覆盖率门禁、评测回归套件 |

---

## 八阶段构建蓝图

```
第一阶段  ●──○ 项目初始化    ▸ 脚手架搭建、AGENTS.md 规范、skills 加载契约
第二阶段  ●──○ LLM 抽象层   ▸ 多供应商客户端 + ModelRouter 强弱路由
第三阶段  ●──○ 工具系统     ▸ 少而精工具、代码执行模式、tool search
第四阶段  ●──○ Agent 核心循环 ▸ 8 个 continue 站点、Verifier 契约、流式事件总线
第五阶段  ●──○ 上下文管理   ▸ 遮蔽优先四级管道 + 压缩台账、Session WAL
第六阶段  ●──○ 权限安全     ▸ 六层纵深防御、沙箱隔离、审计、预算控制
第七阶段  ●──○ 生产化      ▸ 确定性门禁、监控、结构化日志
第八阶段  ●──○ 评测        ▸ 三层指标、judge 校准、CI 回归门禁
```

每阶段包含：**理论指导 → 实践步骤 → 检查清单 → 常见陷阱**

---

## 架构速览

```
┌─────────────────────────────────────────────────────────┐
│                   HARNESS（编排器）                       │
│                   无状态编排循环                           │
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
    │ 追加式事件   │           │   隔离执行   │
    │   日志      │           │    环境     │
    │ 不可变 &    │           │ 文件/网络/  │
    │ 可回放      │           │  进程隔离    │
    └─────────────┘           └─────────────┘
```

**Session（会话）** —— 不可变的追加式事件日志，类似于数据库 WAL，是系统的唯一事实来源。  
**Harness（编排器）** —— 无状态编排循环，崩溃可恢复，可从任意节点重启。  
**Sandbox（沙箱）** —— 隔离执行环境，爆炸半径控制。

---

## 功能特性

<table>
<tr>
<td width="50%">

### 🔒 生产级安全
- **六层纵深防御**安全模型
- 权限模式：`allow` / `deny` / `ask`
- 工具执行前后 Hook 审计
- 沙箱隔离（文件系统、网络、进程）
- 危险命令硬编码拒绝

</td>
<td width="50%">

### 🧠 高级上下文管理
- **遮蔽优先的四级压缩管道**
  - Mask → Snip → Collapse → Autocompact（遮蔽优于摘要：省 52% 成本，还提升 2.6% 解决率）
- 触发阈值 **60-70%**，而非 85%
- 压缩台账：事后可归因"到底丢了什么"
- 外置 scratchpad 记忆，无损存活于任意次压缩
- `tool search` 延迟加载，节省上下文窗口

</td>
</tr>
<tr>
<td width="50%">

### 🔧 多供应商 LLM 支持
- 供应商无关的 `LLMClient` 抽象接口
- Anthropic、OpenAI、Azure、本地模型
- 工厂模式，零代码切换供应商
- 流式（Async Generator）架构

</td>
<td width="50%">

### 🤖 多智能体
- Coordinator 协调者模式 & Swarm 群集模式
- Manager-Worker / Generator-Critic / Debate
- **独立 Evaluator** 角色与对抗式验证
- 子 Agent 上下文隔离，摘要式返回
- MCP **Streamable HTTP**（远程）/ stdio（本地）
- A2A 连 Agent↔Agent，AG-UI 连 Agent↔前端

</td>
</tr>
</table>

---

## templates/ 与 examples/ 的区别

> **两者都不应该被直接复制。** 它们都是骨架：真实签名 + `raise NotImplementedError("AI: ...")` + AI 构建提示。详见上方[禁止复制规则](#-禁止复制规则本项目最核心的差异点)。

| 目录 | 它是什么 | 怎么用 |
|------|---------|--------|
| `templates/minimal/`<br>`templates/professional/`<br>`templates/enterprise/` | **规模脚手架** —— 按 Minimal / Professional / Enterprise 三档裁剪的起始骨架 | 从这里开始。选一档，然后让 AI 自行设计每个模块。 |
| `examples/python/`<br>`examples/nodejs/` | **教学参考** —— 展示"完整架构长什么样"的骨架化对照图 | 用来理解各模块如何协作。**不要**当脚手架用。（v3 里它是 `templates/project-scaffold/`，含完整实现，现已骨架化并移出。） |

```
templates/                    规模脚手架（选一档）
├── minimal/                  ~300-500 行，几乎无三方依赖
├── professional/             ~2000-4000 行，Docker 沙箱、测试、结构化日志
└── enterprise/               ~6000-10000 行，全链路追踪、微 VM、多 Agent

examples/                     教学参考：各模块如何连接
├── python/
│   ├── src/agent/            核心循环、会话、上下文、记忆
│   ├── src/llm/              客户端抽象、工厂、供应商、路由
│   ├── src/tools/            工具注册表、文件工具、网络工具
│   ├── src/permissions/      权限模型、Hook、沙箱
│   ├── src/utils/            日志、错误
│   └── config/ skills/ tests/
└── nodejs/                   与 Python 版镜像的结构
```

### 推荐技术栈（非强制）
- **Python**：`anthropic` · `openai` · `httpx` · `pydantic` · `pyyaml` · `pytest` · `structlog` · `docker` · `promptfoo`/`deepeval`
- **Node.js**：`@anthropic-ai/sdk` · `openai` · `axios` · `js-yaml` · `zod` · `vitest` · `pino` · `dockerode`

完整的三档推荐见 [`references/11-technology-stack.md`](references/11-technology-stack.md)，含评测、追踪、模型路由、沙箱四个新维度。

---

## 十一大设计哲学

1. **Async Generator 流式架构** —— yield 中间事件，而非只返回最终结果
2. **Continue 站点实现状态机** —— `while(true)` + 8 个恢复点（含验证失败），从任意错误中恢复
3. **编译时特性门控** —— 构建时消除死代码
4. **缓存前缀稳定性** —— 内置工具排序后作为稳定前缀，`tool search` 不影响缓存
5. **纵深防御** —— 6 层叠加使绕过概率指数下降
6. **数据驱动可扩展性** —— `settings.json` + `agents/*.md` + `skills/*.md` + hooks
7. **上下文即稀缺资源** —— 遮蔽优先、tool search、外置 scratchpad、四级压缩管道
8. **层级化配置覆盖** —— CLI > Flag > Policy > Managed > Local > Project > User 共 7 级
9. **隔离的子 Agent 上下文** —— 子 Agent 从空白消息列表开始，完成后只返回摘要
10. **可逆性优先** —— 文件编辑通过 Edit（替换字符串），不用 Write（覆盖）
11. **工具少而精，代码执行优于多次工具调用** —— 在沙箱脚本里编排完成，而不是让 N 次往返把中间结果灌进上下文

---

## 适用场景

触发关键词：

> "构建 agent" · "创建智能体" · "agent 系统" · "自动化工具" · "AI 助手" · "多智能体" · "agent 优化" · "agent 脚手架" · "agent 项目模板" · "agent 框架" · **"harness engineering" · "上下文工程" · "Agent 评测" · "长时运行 agent" · "跨会话交接" · "构建 skill" · "agent 成本控制"**

### 使用场景

| 规模 | 说明 | 示例 |
|------|------|------|
| **小型** | 个人助手 | 编程助手、笔记整理 |
| **中型** | 团队工具 | 代码审查机器人、CI/CD 助手 |
| **大型** | 企业平台 | 客服群集、运维自动化舰队 |

---

## 仓库结构

```
SKILL.md          中枢：加载路由表、需求确认、十一大设计哲学
AGENTS.md         给 AI 编程工具的仓库级持久指令
CHANGELOG.md      版本历史（含 v4 破坏性变更）
references/       15 个深度文档（阶段 1-8 + 核心概念 + 运维专题）
templates/        规模脚手架：minimal / professional / enterprise
examples/         骨架化教学参考（禁止直接复制）
evals/            结构化评测套件：scenarios / graders / baseline
```

> 15 个 reference 全量加载会吃掉大量上下文 —— 所以 `SKILL.md` 里提供了**加载路由表**，告诉 AI 当前任务该读哪 2-6 个。本 Skill 自己就在实践它所教的渐进式披露。

---

## 路线图

- [x] 八阶段构建蓝图（v2 → v4）
- [x] Python & Node.js 参考结构
- [x] 多智能体协作模式
- [x] MCP 协议集成 → **Streamable HTTP**、A2A、AG-UI
- [x] 六层纵深防御安全
- [x] 四级上下文压缩管道 → **遮蔽优先**（v4）
- [x] v4 Loop Engineering 升级
- [x] **评测套件与 CI 回归门禁**（v4）
- [x] **确定性验证回路**（v4）
- [x] **预算控制与模型路由**（v4）
- [x] **长时运行与跨会话交接**（v4）
- [ ] Go 语言脚手架
- [ ] 可视化架构图
- [ ] 真实案例研究

---

## 贡献指南

欢迎贡献！你可以通过以下方式参与：

- 添加新语言的脚手架（Go、Rust、TypeScript 原生）
- 完善参考文档
- 添加评测用例
- 分享使用此 Skill 构建的真实 Agent 案例

提交 PR 前请阅读[贡献指南](CONTRIBUTING.md)。

---

## 开源协议

本项目基于 Apache License 2.0 开源协议 — 详见 [LICENSE](LICENSE)。

---

<p align="center">
  <sub>由 Agent 工程社区 ❤️ 构建</sub>
  <br />
  <sub>如果这个项目对你有帮助，请在 GitHub 上 ⭐ Star 支持！</sub>
</p>