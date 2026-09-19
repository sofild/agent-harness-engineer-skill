---
name: agent-harness-engineer
description: >
  指导AI coding工具构建生产级Agent系统。当用户需要设计、实现或优化AI Agent系统时触发。
  特别适用于：Agent架构设计、Harness工程、工具系统、权限模型、上下文管理、多智能体协作、
  记忆系统、安全沙箱、MCP集成、Agent评测、长时运行等场景。支持从概念设计到生产部署的完整Agent系统构建。

  触发关键词：构建agent、创建智能体、agent系统、自动化工具、AI助手、多智能体、
  agent优化、升级agent、agent脚手架、agent项目模板、agent框架、
  harness engineering、上下文工程/context engineering、Agent评测/agent eval、
  长时运行/long-running agent、跨会话交接、agent skills构建、工具设计、成本预算控制。

  核心目标：帮助AI coding工具生成结构完整、可扩展、生产就绪的Agent项目，
  并证明它可靠、可控、在预算内，而非仅提供最小化demo代码。

  版本演进：
  - v1版本：提供理论文档和最小示例，AI coding工具需要自己理解如何应用
  - v2版本：提供分阶段构建指南，每个阶段都有明确的理论指导、实践步骤、检查清单和常见问题
  - v3版本：引入三级构建规模、代码生成禁止复制策略、技术栈分级推荐、抽象接口引导模式
  - v4版本（当前）：补齐评测(Phase 8)、确定性验证回路、预算模型、长时运行跨会话交接四大结构缺口；
    修正两处范式方向——上下文压缩改为"遮蔽优先"且阈值下调到60-70%、工具系统从"多而全"反转为
    "少而精+代码执行"；统一错误分类(ErrorKind)与可重试语义；同步Agent Skills开放标准、
    MCP 2026(Streamable HTTP)/A2A/AG-UI；消除文档内部矛盾。
    AI coding工具必须根据用户需求生成定制化代码，不得直接复制reference或example中的代码。
---

# Agent Harness Engineer v4

本 Skill 将帮助你设计、实现和优化生产级的 AI Agent 系统，当前是 v4 版本。

本版本采用**分阶段构建模式**，将 Agent 系统构建拆分为 8 个明确的阶段，每个阶段都有：
- **理论指导**：该阶段需要应用什么设计原则
- **抽象接口层**：定义而非实现，引导 AI 根据需求生成代码（铁律）
- **AI 构建提示**：在关键位置给出引导，告诉 AI 应该生成什么
- **检查清单**：完成标准是什么（按规模分级）
- **常见问题**：这个阶段容易踩什么坑

## v4 变更摘要（相对 v3）

| 类别 | 变更 | 影响的文件 |
|------|------|-----------|
| **结构补齐** | 新增 **Phase 8 评测与回归门禁**（三层指标、四类用例矩阵、judge 校准、pass^k、CI 门禁） | 新增 `15-evaluation.md`，重构 `evals/` |
| **结构补齐** | 新增**确定性验证回路**（CONTINUE-SITE-8、Verifier 契约、guides & sensors） | `04`、`07` |
| **结构补齐** | 新增**预算与成本控制模型**（Budget / 四级降级链 / ModelRouter） | `06`、`02` |
| **结构补齐** | **长时运行与跨会话交接**（handoff 文件、feature list、五步初始化仪式） | `13` 重构并更名 |
| **范式修正** | 压缩管道**遮蔽优先**（Mask → Snip → Collapse → Autocompact），阈值 85% → **60-70%**，新增压缩台账 | `05` |
| **范式反转** | 工具从"多而全"到"**少而精 + 代码执行**"，工具数量建议下调 | `03`、`08` |
| **维度补齐** | 可观测性从性能到**质量**（8 个质量指标、生产回流、阻断类断点不放行、日志脱敏） | `14` |
| **抽象补齐** | 统一**错误分类 ErrorKind** 五类枚举与可重试语义 | `08` |
| **标准对齐** | Agent Skills **渐进式披露** + AGENTS.md 定位 | `01`、`08` |
| **角色补齐** | 多 Agent 新增**独立 Evaluator** 与对抗式验证 | `09` |
| **生态同步** | MCP 2026（**Streamable HTTP** 为远程默认）、A2A、AG-UI | `10`、`12` |
| **一致性** | 消除安全层双模型、沙箱数据单一事实源、版本统一、模板体系整改 | `06`、`12`、`examples/` |

> **破坏性变更**：`references/13-session-design.md` 已更名为 `references/13-long-running-session.md`；
> `templates/project-scaffold/` 已更名为仓库根的 `examples/`（教学参考，**非脚手架**）。详见 `CHANGELOG.md`。
- **理论指导**：该阶段需要应用什么设计原则
- **抽象接口层**：定义而非实现，引导 AI 根据需求生成代码（v3 核心变更）
- **AI 构建提示**：在关键位置给出引导，告诉 AI 应该生成什么
- **检查清单**：完成标准是什么（按规模分级）
- **常见问题**：这个阶段容易踩什么坑

## v3 核心变更（必读）

### 变更1：三级构建规模

Agent 系统不再只有一种构建方式。根据用户需求，分为三级：

```
┌───────────────────┬───────────────────────┬──────────────────────────┬──────────────────────────┐
│  维度             │  Minimal（最小）       │  Professional（专业）     │  Enterprise（企业）       │
├───────────────────┼───────────────────────┼──────────────────────────┼──────────────────────────┤
│  目标             │  快速原型/学习验证     │  团队工具/生产级应用      │  企业平台/高并发/多租户   │
│  预期代码量       │  ~300-500行           │  ~2000-4000行            │  ~6000-10000行+          │
│  第三方库         │  仅SDK（1-2个）       │  5-8个关键库             │  10+个全套生态栈         │
│  沙箱             │  路径白名单检查        │  Docker容器隔离           │  Firecracker微VM隔离      │
│  日志             │  print() / console.log│ structlog / loguru / pino│  OpenTelemetry 全链路     │
│  CLI              │  input() / 简单argparse│ click / typer / commander│  rich + 交互式TUI         │
│  配置管理         │  .env 文件            │  YAML + pydantic/zod     │  7级层级化配置覆盖        │
│  测试             │  手动测试或无          │  pytest/jest + mock      │  pytest/jest + CI/CD      │
│  监控             │  无                   │  基础 metrics 计数器     │  Prometheus + Grafana     │
│  上下文压缩       │  仅 Mask（结果遮蔽） │  Mask→Snip→Collapse→ │  四级 + 压缩台账 + 恢复   │
│  记忆系统         │  无                   │  文件系统持久化 + 外置  │  向量数据库 + 自动做梦    │
│  MCP集成          │  无                   │  stdio / Streamable   │  全协议 + tool search    │
│  多Agent          │  不支持               │  可选（Coordinator）   │  Coordinator+Swarm+Eval  │
│  确定性验证       │  无                   │  compile/lint/test    │  全门禁 + Evaluator角色   │
│  评测             │  5-10条手工冒烟       │  30-100条 + CI门禁    │  100-1000条 + 生产采样    │
│  预算控制         │  无                   │  Budget + 两级降级    │  Budget + 四级降级链      │
│  长时运行/跨会话  │  不涉及               │  会话内 progress 文件  │  Initializer/Coding 双角色│
└───────────────────┴───────────────────────┴──────────────────────────┴──────────────────────────┘
```

### 变更2：代码生成禁止复制策略

> **关键规则：AI coding工具必须根据用户需求设计并生成代码，不得直接复制 reference、template 或 example 文件中的代码片段。**
> 
> Reference 文件中的代码已从"完整实现"改为"抽象接口/类定义 + AI构建提示"（`raise NotImplementedError("AI: ...")`）。
> Template 文件中的代码已从"完整实现"改为"骨架 + TODO + AI构建提示"。
> `examples/` 目录中是**已全面骨架化**的教学参考（v4 已将原 `templates/project-scaffold/` 更名而来），用于理解模块如何协作，**同样禁止直接复制**。
>
> **为什么？** 之前的 reference 和 template 中包含完整可运行代码（如 read_file 实现、sandbox 实现），AI工具会直接复制，导致生成的系统永远是"最小实现"，无法根据用户需求调整复杂度和技术栈。更危险的是那些实现缺少安全约束（例如不带路径白名单的文件读取），会被当作正确范式学走。

**AI coding工具的正确行为：**
1. 阅读 reference 中的抽象接口定义，理解需要哪些方法和属性
2. 阅读 reference 中的设计原理，理解为什么这样设计
3. 根据用户选择的规模和用途，决定生成代码的复杂度和完整度
4. 参考 technology-stack.md 选择合适的三方库
5. **自己设计并编写代码**，而非复制粘贴

### 变更3：技术栈分级推荐

参考 `references/11-technology-stack.md`，每个维度（日志、CLI、HTTP、沙箱、监控等）都提供 Minimal / Professional / Enterprise 三级推荐方案。AI 必须根据用户选择的规模，选择对应级别的技术栈。

## 快速导航

- **[SKILL.md](SKILL.md)** (本文件): 核心原则、构建规模分级、代码生成策略、reference 加载路由表
- **[references/01-phase-init.md](references/01-phase-init.md)**: Phase 1: 项目初始化（三级规模目录结构、AGENTS.md 规范、skills 渐进式披露）
- **[references/02-phase-llm.md](references/02-phase-llm.md)**: Phase 2: LLM抽象层（含streaming、retry、token计数、ModelRouter）
- **[references/03-phase-tools.md](references/03-phase-tools.md)**: Phase 3: 工具系统（少而精原则、CodeExecution模式、tool search、MCP adapter）
- **[references/04-phase-agent-loop.md](references/04-phase-agent-loop.md)**: Phase 4: Agent核心循环（含状态机、**8个continue站点**、Verifier契约、流式架构）
- **[references/05-phase-context.md](references/05-phase-context.md)**: Phase 5: 上下文管理（**Mask→Snip→Collapse→Autocompact**四级管道、压缩台账、Session WAL）
- **[references/06-phase-permissions.md](references/06-phase-permissions.md)**: Phase 6: 权限安全（含5种模式、7级规则、6层防御、**预算控制**）
- **[references/07-phase-production.md](references/07-phase-production.md)**: Phase 7: 生产化（含确定性门禁清单、OpenTelemetry、三层可观测、CI/CD）
- **[references/08-core-concepts.md](references/08-core-concepts.md)**: 核心概念速查（三大支柱、三组件虚拟化、**ErrorKind错误分类**、十一条设计哲学）
- **[references/09-multi-agent.md](references/09-multi-agent.md)**: 多智能体（子Agent隔离、**独立Evaluator**、对抗式验证、Token节省量化）
- **[references/10-mcp-integration.md](references/10-mcp-integration.md)**: MCP集成（**Streamable HTTP**、A2A/AG-UI选型、连接池、OAuth）
- **[references/11-technology-stack.md](references/11-technology-stack.md)**: 技术栈分级选择指南（日志/CLI/HTTP/沙箱/监控/测试/**评测/追踪/路由**）
- **[references/12-sandbox-advanced.md](references/12-sandbox-advanced.md)**: 沙箱深度设计（跨平台矩阵、Firecracker/gVisor/Wasm/**microsandbox**、红队自检）
- **[references/13-long-running-session.md](references/13-long-running-session.md)**: 长时运行与会话设计（WAL模式、事件类型、**跨会话handoff**、feature list、五步初始化仪式）
- **[references/14-observability.md](references/14-observability.md)**: 可观测性（质量指标层、生产回流、OpenTelemetry/Prometheus/Langfuse、日志脱敏）
- **[references/15-evaluation.md](references/15-evaluation.md)**: **Phase 8**: Agent评测与回归门禁（三层指标、四类用例矩阵、judge校准、pass^k、CI门禁）
- **[templates/minimal/](../templates/minimal/)**: Minimal 规模脚手架模板
- **[templates/professional/](../templates/professional/)**: Professional 规模脚手架模板
- **[templates/enterprise/](../templates/enterprise/)**: Enterprise 规模脚手架模板
- **[examples/](../examples/)**: 完整架构**教学参考**（已骨架化，**禁止直接复制**，仅用于理解各模块如何协作）
- **[evals/](../evals/)**: 结构化评测套件（scenarios / graders / baseline）

### reference 加载路由表（渐进式披露，务必遵守）

> 本 Skill 自身就在教"渐进式披露"。reference 共 15 个，全量加载会吃掉大量上下文。
> **按任务类型只加载必读文件，选读文件仅在需要时才打开。**

| 你要做的事 | 必读 | 选读 |
|-----------|------|------|
| 从零构建完整 Agent 系统 | `SKILL.md`、`01`、`03`、`04`、`05`、`06` | `02`、`07`、`08`、`11` |
| 只设计/改造工具系统 | `03`、`08` | `10`、`12` |
| 只做上下文管理/压缩 | `05`、`13` | `06`、`14` |
| 只做权限与沙箱安全 | `06`、`12` | `08`、`10` |
| 构建/优化多 Agent 协作 | `09`、`04` | `10`（A2A）、`08` |
| 接入 MCP / 选型协议 | `10` | `03`、`09`、`12` |
| 加评测、证明可靠性 | `15`、`14` | `07`、`09` |
| 长时运行 / 跨会话续跑 | `13`、`05` | `06`、`15` |
| 成本失控、需要预算控制 | `06`、`02`、`14` | `05`、`08` |
| 上线后可观测与质量退化排查 | `14`、`15` | `09`、`06` |
| 选择技术栈 | `11` | `01`、`12` |

每个 reference 的章节开头都标注了"何时读本章"，可据此进一步收缩阅读范围。

## 核心原则

### 1. Harness Engineering 三大支柱

- **Context Engineering（上下文工程）**: 管理信息的可访问性、结构和时机
  - 静态上下文：CLAUDE.md/AGENTS.md、设计文档
  - 动态上下文：日志、指标、Git状态、CI/CD状态
  - 上下文压缩：四级管道（**Mask 遮蔽 → Snip → Collapse → Autocompact**，见 `references/05-phase-context.md`）
  - 外置记忆：压缩的无损安全网——"Notes survive compaction losslessly; summaries do not."
  - 核心原则: "Agent无法在上下文中访问的信息不存在"

- **Architectural Constraints（架构约束）**: 通过机械执行而非建议来建立边界
  - 权限模型：5种模式 × 7级规则层级
  - 工具约束：Schema验证、并发安全标记
  - 安全边界：沙盒隔离、硬编码拒绝、纵深防御（6层）

- **Entropy Management（熵管理）**: 定期清理Agent解决代码退化
  - 文档一致性验证、约束违规扫描、模式强制执行
  - 依赖审计、性能监控、覆盖率守卫

### 2. 三组件虚拟化架构

```
Session（会话）= 追加式事件日志（Append-only Event Log）
  - 不可变、可序列化、可回放
  - 类似数据库WAL，是系统的唯一事实来源
  - 支持故障恢复、负载迁移、调试回放

Harness（编排器）= 无状态编排循环
  - 全部输入来自Session日志
  - 可随时崩溃、重启、迁移
  - 给定同样的Session日志，任何实例都会做出同样决策

Sandbox（沙箱）= 隔离执行环境
  - 文件系统隔离、网络隔离、进程隔离
  - 凭证外置，按需创建和销毁
  - 限制爆炸半径（Blast Radius Containment）
```

## 需求确认（构建前的必要步骤）

> **重要：在开始构建Agent之前，必须先确认用户需求。**
> **如果用户已经明确提供了以下信息，可以跳过本环节。**
> **如果用户没有提供，AI coding工具必须主动询问用户做选择，不得自行决定。**

### 需要确认的问题

当用户说"帮我构建一个Agent"但没有明确说明以下信息时，AI coding工具必须主动询问：

| 问题 | 选项/说明 | 影响 |
|------|---------|------|
| **技术栈偏好？** | Python / Node.js / TypeScript / Go | 决定项目脚手架语言 |
| **LLM供应商？** | Anthropic / OpenAI / Azure / 本地模型 | 决定默认配置 |
| **构建规模？** | Minimal / Professional / Enterprise | 决定项目复杂度、代码量、三方库数量 |
| **主要用途？** | 编码助手 / 自动化运维 / 数据分析 / 通用对话 / 其他 | 决定工具集 |
| **部署环境？** | 本地 / 云服务器 / 容器 / Serverless | 决定配置方式 |
| **沙箱隔离需求？** | 无 / 基础路径检查 / Docker隔离 / Firecracker微VM | 决定安全方案 |
| **监控需求？** | 无 / 基础日志 / 全链路追踪(Prometheus+OpenTelemetry) | 决定可观测方案 |
| **是否需要多Agent协作？** | 是 / 否 | 决定是否需要 `09` 内容 |
| **是否需要评测 / 有无合规要求？** (v4) | 不需要 / 手工冒烟 / CI回归门禁 / 生产采样+趋势告警 | 决定 Phase 8 的深度与合规证据要求 |
| **单次任务成本预算上限？** (v4) | 不限 / 有上限（请给出：token 数或美元 / 最大轮次 / 最长墙钟时间） | 决定 Budget 与四级降级链是否启用 |
| **是否需要长时运行 / 跨会话续跑？** (v4) | 否（单会话内完成）/ 是（跨天、需断点续跑） | 决定是否引入 `13` 的 handoff 文件与双角色模型 |

### 询问示例

如果用户说"帮我构建一个Agent"，但没有提供上述信息，AI coding工具应该这样询问：

```
在开始构建Agent之前，我需要确认几个问题：

1. **技术栈偏好**：
   - Python（推荐，功能完善）
   - Node.js/TypeScript

2. **LLM供应商**：
   - Anthropic (Claude) - 复杂推理、长上下文
   - OpenAI (GPT) - 通用任务、生态丰富
   - Azure OpenAI - 企业合规
   - 本地模型 (Ollama/vLLM) - 隐私敏感

3. **构建规模**（重要！决定生成代码的复杂度和技术栈）：
   - Minimal：快速原型，~300行代码，几乎无三方库依赖
   - Professional：生产级应用，~3000行代码，包含Docker沙箱、日志系统、测试
   - Enterprise：企业平台，~8000行代码，全链路监控、微VM沙箱、多Agent

4. **主要用途**：编码助手 / 自动化运维 / 数据分析 / 通用对话 / 其他

5. **沙箱隔离需求**：
   - 不需要（Agent在本地直接执行）
   - 基础路径检查（沙箱限制工作目录）
   - Docker容器隔离（推荐Professional场景）
   - Firecracker微VM（推荐Enterprise高安全场景）

6. **监控需求**：
   - 不需要
   - 基础结构化日志（推荐Professional场景）
   - 全链路追踪（推荐Enterprise场景）

7. **是否需要多Agent协作**？
   - 是 / 否

8. **是否需要评测 / 有无合规要求**？（决定如何证明它可靠）
   - 不需要（原型验证阶段）
   - 手工冒烟（5-10 条关键路径）
   - CI 回归门禁（每次改动跑评测套件，防退化）
   - 生产采样 + 趋势告警（上线后持续监控质量漂移）

9. **单次任务成本预算上限**？（防止长时/多Agent场景成本失控）
   - 不限
   - 有上限（请给出：最大 token 数 / 美元数 / 最大轮次 / 最长运行时间）

10. **是否需要长时运行或跨会话续跑**？
   - 否（任务在单个会话内完成）
   - 是（跨天、需要断点续跑与交接文件）

请告诉我你的选择，我会根据你的需求构建最合适的Agent项目。
```

### 快速确认模式

如果用户已经提供了部分信息，AI coding工具只需要补充询问未提供的信息：

```
根据你的需求（Python技术栈 + Anthropic模型 + 编码助手），
我还需要确认：

1. 构建规模？
   - Minimal：快速原型（300行）
   - Professional：生产级（3000行）
   - Enterprise：企业平台（8000行）

2. 沙箱隔离需求？
   - 无 / 基础路径检查 / Docker隔离 / Firecracker微VM

3. 监控需求？
   - 无 / 基础日志 / 全链路追踪

4. 是否需要多Agent协作？
   - 是 / 否

请补充提供以上信息，我将开始构建。
```

### 默认值策略

如果用户没有明确偏好，AI coding工具可以建议默认值，但必须说明原因：

```
你未明确说明偏好，我将使用以下默认值：
- 技术栈：Python（功能完善，社区活跃）
- LLM供应商：Anthropic（长上下文优势）
- 构建规模：Professional（平衡功能与复杂度，适合团队工具阶段）
- 主要用途：通用对话
- 沙箱：Docker隔离
- 监控：基础结构化日志
- 多Agent协作：否
- 评测：CI 回归门禁（推荐 Professional 及以上）
- 成本预算：不限制，但记录 cost_per_task 作为基线（推荐）
- 长时运行：否（单会话内完成）

如果你有其他偏好，请在回复中说明，我会相应调整。
```

### 构建规模决策矩阵

AI可以辅助用户选择规模：

```
┌─────────────────────────────────────────────────────────────┐
│ 帮你选择构建规模：                                            │
│                                                              │
│ ● 如果你是开发者，想快速验证Agent概念 → Minimal               │
│ ● 如果你是团队，需要可维护的生产级Agent → Professional        │
│ ● 如果你是平台方，需要服务多用户 → Enterprise                 │
│                                                              │
│ 如果你不确定，建议从 Professional 开始。                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 分阶段构建指南

> **核心规则（v4 强制）**：
> 1. 以下每个 Phase 的摘要仅提供目标概述。**实际构建时必须按 reference 加载路由表打开对应的 reference 文件**，其中包含设计原理、抽象接口定义、AI构建提示。**不要一次性全量加载 15 个 reference。**
> 2. **禁止直接复制 reference、template 或 example 中的代码片段。** AI 必须根据用户选择的规模生成定制化代码。
> 3. 每个阶段完成后，必须使用**与该规模对应的检查清单**进行验收。
> 4. **每个 Phase 验收时都要回答：这一段有没有客观证据？** 能量化的（编译通过、测试通过、评测分数、成本）一律用机器判定，不要用"看起来没问题"代替。

### Phase 1: 项目初始化 → `references/01-phase-init.md`

**目标**：建立项目骨架，定义目录结构（三级规模不同结构）和配置文件。

**规模差异**：
- Minimal: 单文件或最小目录结构
- Professional: 标准 src/config/tests 分离
- Enterprise: 多包 monorepo 结构

### Phase 2: LLM抽象层 → `references/02-phase-llm.md`

**目标**：实现与供应商无关的LLM客户端抽象。

**规模差异**：
- Minimal: 单一供应商直连
- Professional: 工厂模式 + streaming + retry
- Enterprise: 多供应商 + prompt cache管理 + token计数 + lazy import

### Phase 3: 工具系统 → `references/03-phase-tools.md`

**目标**：实现模块化的工具注册和执行机制。

**规模差异**：
- Minimal: 函数字典注册
- Professional: Registry + Schema验证 + MCP adapter
- Enterprise: 并发分区算法 + 工具依赖图 + 工具结果truncation

### Phase 4: Agent核心循环 → `references/04-phase-agent-loop.md`

**目标**：实现健壮的Agent主循环，融合2026年九大Loop Engineering技术。

**规模差异**：
- Minimal: 简单 while 循环 + 声明式配置概念 + 基础安全检查点
- Professional: 轻量图配置 + 双层循环（简化版） + 安全护栏（简化版） + 声明式配置
- Enterprise: 全9大技术 + 流式事件总线 + 耐久执行 + DSPy自优化 + 可观测断点 + 多Agent拓扑

### Phase 5: 上下文管理 → `references/05-phase-context.md`

**目标**：实现四级压缩管道和记忆系统。

**规模差异**：
- Minimal: 仅 Snip 历史截断
- Professional: 完整四级管道 + 文件记忆
- Enterprise: 四级 + 压缩状态恢复 + 向量数据库记忆

### Phase 6: 权限安全 → `references/06-phase-permissions.md`

**目标**：实现权限控制和沙箱机制。

**规模差异**：
- Minimal: 命令黑名单
- Professional: 权限模型 + Hook系统 + Docker沙箱
- Enterprise: 6层纵深防御 + Firecracker + 审计日志

### Phase 7: 生产化 → `references/07-phase-production.md`

**目标**：添加测试、监控、日志，并把 compile/lint/type/test 建成**输出机器可解析**的确定性门禁。

**规模差异**：
- Minimal: 无
- Professional: pytest + structlog + 基础metrics + 确定性门禁
- Enterprise: CI/CD + OpenTelemetry + Prometheus + 全门禁（架构检查、安全扫描）

### Phase 8: 评测与回归门禁 → `references/15-evaluation.md`

**目标**：证明 Agent 可靠，而不只是"看起来能用"。**评轨迹，不只是评答案。**

**规模差异**：
- Minimal: 5-10 条手工冒烟场景
- Professional: 30-100 条 + CI 门禁（无回归 + 成本在带宽内）
- Enterprise: 100-1000 条 + 生产采样 1-5% + 趋势告警

## 十一大设计哲学

1. **Async Generator流式架构**: 不是返回最终结果，而是yield每一个中间事件
2. **通过Continue站点实现状态机**: while(true) + 8个continue站点（第8个是验证失败）
3. **编译时特性门控**: if (feature('FEATURE_X')) // bun:bundle编译时求值
4. **缓存前缀稳定性**: 内置工具排序后作为稳定前缀，MCP工具变化不影响缓存
5. **纵深防御**: 6层叠加使绕过概率指数下降
6. **数据驱动的可扩展性**: settings.json + agents/*.md + skills/*.md + hooks
7. **上下文即稀缺资源**: 工具延迟加载、记忆按需附加、四级压缩管道
8. **层级化配置覆盖**: 7级设置，CLI > Flag > Policy > Managed > Local > Project > User
9. **隔离的子Agent上下文**: 子Agent从空白消息列表开始，完成后只返回摘要
10. **可逆性优先**: 文件编辑通过Edit（替换字符串），不是Write（覆盖）
11. **工具少而精，代码执行优于多次工具调用** (v4新增): 少数强大工具 >> 大量狭窄工具；能用一个脚本在沙箱里编排完成的事，不要用十次工具往返把中间结果灌进上下文。工具数量与准确率成反比（详见 `references/03-phase-tools.md`）

## 常见陷阱

1. **不要在Stop hook中做太重的操作**: 可能触发prompt-too-long错误，导致逻辑被静默跳过
2. **Hook allow不能绕过deny规则**: deny > settings rules > hook allow，这是安全不可变量
3. **Hook 超时/失败一律降级为 DENY**（v4 修正）: 超时放行等于给绕过留了一个通往 Layer1 硬编码 deny 之外的口子；正确做法是 deny 或升级为人工审批
4. **hasAttemptedReactiveCompact不重置**: 防止compact→仍然太长→error→stop hook→compact的无限循环
5. **数组合并策略是连接+去重，而非替换**: 权限规则需要累加而非覆盖
6. **沙盒设置文件被硬编码为不可写**: 防止Agent通过修改settings.json来关闭沙盒
7. **MCP工具默认使用always_ask**: 第三方工具不应被自动信任
8. **Prompt Cache有最小长度要求**: 约1024 token，太短的前缀不会被缓存
9. **上下文压缩后必须主动恢复关键状态**: 文件内容、Skill上下文、Plan、任务列表
10. **重建上下文时 head 必须逐字节不变**（v4）: system prompt + 任务陈述的改动会静默摧毁前缀缓存经济
11. **只做单输出评分会漏掉四类失败**（v4）: 选错工具但话术流畅、工具对参数错、工具报错被无视后幻觉、前后轮自相矛盾——必须评轨迹
12. **无限重试是最常见的成本事故来源**（v4）: 每个错误路径都必须声明 ErrorKind、最大重试次数与幂等性
13. **不要让生成者评价自己的产出**（v4）: Agent 天然是过于乐观的自我评估者，优先用确定性验证，主观维度交给独立 Evaluator
14. **工具越多准确率越低**（v4）: 先砍到最小可用集，只有当某类任务反复失败才加工具

## 参考资源

- **核心文档**: 本目录下的 `references/` 文件（共15个）+ 前文的 **reference 加载路由表**
- **项目模板**: `templates/minimal/` `templates/professional/` `templates/enterprise/`
- **教学参考（禁止直接复制）**: `examples/` —— 完整架构的骨架化对照图
- **评测套件**: `evals/`（scenarios / graders / baseline）
- **变更记录**: `CHANGELOG.md`
- **外部资源**:
  - Anthropic Managed Agents API文档
  - Claude Code源码（~512,664行TypeScript）
  - MCP协议规范（2025-12 起由 Linux Foundation 的 Agentic AI Foundation 治理）
  - Agent Skills 开放标准（agentskills.io）
  - "Scaling Managed Agents: Decoupling the brain from the hands" - Anthropic技术论文
  - "Effective context engineering for AI agents" - Anthropic工程博客
  - "The Complexity Trap" (arXiv 2508.21433) - JetBrains，遮蔽 vs 摘要的对照实验
  - τ-bench - 函数调用 Agent 的 pass^k 可靠性基准