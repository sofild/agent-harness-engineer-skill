# 技术栈分级选择指南

本文件帮助 AI 工具根据用户的构建规模选择合适的技术库。

**何时读本节**：当你已确定构建规模（Minimal / Professional / Enterprise），需要为某一项能力（日志、CLI、HTTP、沙箱、评测、追踪、模型路由等）挑选具体库时使用本表。本表是**选型表**——只给推荐与替代，**不含任何可运行实现**，完整设计见各 `references/xx-name.md`。

**检查维护状态（选型前置判据）**：任何推荐项入库前都必须满足以下判据，与本文件反模式表「选择已弃用的库」呼应：

- **最近一次 release**：过去 12–18 个月内有正式发布（已弃用库通常停更 2 年以上）。
- **issue / PR 响应速度**：核心 issue 数周内有人响应，安全 issue 有及时处理记录。
- **已知 CVE**：无未修复高危漏洞，或上游已提供官方补丁与公告。
- **官方推荐度**：是否进入框架/生态的官方推荐列表，或仍有活跃维护者背书。
- 任一判据不达标 → 标注「检查维护状态」并优先选用替代项；**已确认弃用（如 `vm2`）必须移除**。

---

## Python 生态

### 日志 (Logging)

| 级别 | 推荐 | 替代 | 说明 |
|---|---|---|---|
| **Minimal** | `print()` | — | 零依赖，适合脚本级项目 |
| **Professional** | `structlog` | `loguru` | 结构化日志，支持上下文绑定 |
| **Enterprise** | `structlog` + OpenTelemetry | `loguru` + otel | 全链路追踪，日志关联 trace_id |

选择依据：
- Minimal：代码量 < 500 行，仅需基础调试输出
- Professional：需要 JSON 格式日志输出到文件或日志收集器
- Enterprise：多服务/多 Agent 协同，需要关联追踪和集中日志平台

### CLI (命令行接口)

| 级别 | 推荐 | 替代 | 说明 |
|---|---|---|---|
| **Minimal** | `input()` + `argparse` | — | 标准库，无需安装 |
| **Professional** | `click` | `typer` | 装饰器风格，自动生成 help |
| **Enterprise** | `typer` + `rich` | `click` + `rich` | 类型安全 + 美化 TUI 输出 |

选择依据：
- Minimal：单命令脚本，参数 ≤ 3 个
- Professional：多子命令，需要 `--help` 自动生成
- Enterprise：复杂 CLI Tree，需要进度条/表格/颜色输出

### HTTP Client

| 级别 | 推荐 | 替代 | 说明 |
|---|---|---|---|
| **Minimal** | `urllib` (标准库) | — | 基本 HTTP 请求 |
| **Professional** | `httpx` (async) | `aiohttp` | 异步优先，HTTP/2 支持 |
| **Enterprise** | `httpx` + 连接池 | `aiohttp` | 连接复用，超时重试策略 |

选择依据：
- Minimal：单次 API 调用，无需异步
- Professional：并发请求，需要 async/await
- Enterprise：高并发，需要连接池管理和熔断器

### Schema / Validation (数据验证)

| 级别 | 推荐 | 替代 | 说明 |
|---|---|---|---|
| **Minimal** | 无 | — | 手动类型检查 |
| **Professional** | `dataclasses` | `attrs` | 类型注解，零依赖 |
| **Enterprise** | `pydantic` v2 | `msgspec` | 运行时验证 + JSON Schema 导出 |

选择依据：
- Minimal：简单数据结构，字段 ≤ 5 个
- Professional：嵌套对象，需要类型安全
- Enterprise：API 契约验证，需要序列化/反序列化保证

### Testing (测试)

| 级别 | 推荐 | 替代 | 说明 |
|---|---|---|---|
| **Minimal** | 无 | — | 手动测试或 `assert` |
| **Professional** | `pytest` + `pytest-asyncio` | `unittest` | fixture + mock 支持 |
| **Enterprise** | `pytest` + `coverage` + `tox`/`nox` | — | CI/CD 集成，多 Python 版本矩阵 |

选择依据：
- Minimal：探索性代码，无持续维护需求
- Professional：需要回归测试，异步代码覆盖
- Enterprise：多环境矩阵测试，覆盖率门禁 (≥ 80%)

### 沙箱 (Sandbox)

> **何时读本节**：实现 Agent 工具执行隔离前读本节，并**以 `references/12-sandbox-advanced.md` 为事实源**（三层隔离模型、跨平台矩阵、资源限额、逃逸自检均在该文件）。本表只做选型，隔离细节与实现约束以 12 为准。

| 级别 | 推荐 | 替代 | 说明 |
|---|---|---|---|
| **Minimal** | 路径白名单 | — | 纯 Python 实现（PathResolver），~50 行，无进程隔离（见 12 Minimal） |
| **Professional** | `docker-py` | `dockerode` / bubblewrap | 容器或命名空间隔离，~200 行（见 12 Professional） |
| **Enterprise** | Firecracker SDK / microsandbox | gVisor runtime | 微 VM / 用户态内核隔离，~500 行（见 12 Enterprise；microsandbox 为跨平台 Rust 微 VM） |

选择依据：
- Minimal：信任级别高，仅需文件路径保护
- Professional：需要进程级隔离，多租户场景
- Enterprise：零信任环境，需要内核级隔离和凭证外置

> ⚠ 沙箱选型**必须与 `references/12-sandbox-advanced.md` 保持一致**，不得在本表另起一套隔离方案。WASM/WASI 沙箱（指令级、零冷启动、跨平台）适用于插件/受限逻辑，见 12「2026 新沙箱选项」。

### 监控 (Monitoring)

| 级别 | 推荐 | 替代 | 说明 |
|---|---|---|---|
| **Minimal** | 无 | — | — |
| **Professional** | `prometheus-client` | 自定义 metrics | 指标导出到 `/metrics` |
| **Enterprise** | OpenTelemetry + Prometheus + Grafana | Datadog | 全链路可观测 |

选择依据：
- Minimal：个人使用，无监控需求
- Professional：需要基础指标（请求量/延迟/错误率）
- Enterprise：需要告警规则、Dashboard、Trace 关联

### 配置管理 (Configuration)

| 级别 | 推荐 | 替代 | 说明 |
|---|---|---|---|
| **Minimal** | `python-dotenv` | `os.environ` | `.env` 文件加载 |
| **Professional** | `PyYAML` + `pydantic-settings` | — | YAML 配置 + 类型验证 |
| **Enterprise** | `pydantic-settings` + 7 级层级覆盖 | — | 多源合并 (默认 < 文件 < 环境变量 < 命令行 < 远程) |

选择依据：
- Minimal：配置项 ≤ 5 个，仅需环境变量
- Professional：多环境配置 (dev/staging/prod)，YAML 管理
- Enterprise：配置中心集成，动态热更新

### 数据库 (可选，用于记忆/日志持久化)

| 级别 | 推荐 | 替代 | 说明 |
|---|---|---|---|
| **Minimal** | 无 | — | 文件系统存储 (JSON/JSONL) |
| **Professional** | SQLite (`aiosqlite`) | — | 嵌入式，无需运维 |
| **Enterprise** | PostgreSQL (`asyncpg`) | CockroachDB | 生产级，支持连接池和副本 |

选择依据：
- Minimal：无持久化需求或文件即够用
- Professional：需要 SQL 查询能力，单机部署
- Enterprise：需要高可用、备份恢复、水平扩展

---

## Node.js / TypeScript 生态

### 日志 (Logging)

| 级别 | 推荐 | 替代 | 说明 |
|---|---|---|---|
| **Minimal** | `console.log()` | — | 内建 API |
| **Professional** | `pino` | `winston` | 高性能 JSON 日志 |
| **Enterprise** | `pino` + OpenTelemetry | `winston` + otel | 分布式追踪集成 |

### CLI

| 级别 | 推荐 | 替代 | 说明 |
|---|---|---|---|
| **Minimal** | `process.argv` | — | 手动解析 |
| **Professional** | `commander` | `yargs` | 声明式命令定义 |
| **Enterprise** | `oclif` + `ink` | `commander` + `chalk` | 框架级 CLI + React TUI |

### HTTP Client

| 级别 | 推荐 | 替代 | 说明 |
|---|---|---|---|
| **Minimal** | `fetch` (内建) | — | Node 18+ 原生支持 |
| **Professional** | `undici` | `axios` | 高性能 HTTP 客户端 |
| **Enterprise** | `undici` + 连接池 | `got` | 连接复用 + 重试策略 |

### Schema / Validation

| 级别 | 推荐 | 替代 | 说明 |
|---|---|---|---|
| **Minimal** | 无 | — | TypeScript 类型注解 |
| **Professional** | `zod` | `yup` | 运行时验证 + 类型推导 |
| **Enterprise** | `zod` + `typebox` | `io-ts` *(检查维护状态：fp-ts 生态已进入维护模式，新项目优先 `typebox`)* | JSON Schema 生成 |

### Testing

| 级别 | 推荐 | 替代 | 说明 |
|---|---|---|---|
| **Minimal** | 无 | — | 手动测试 |
| **Professional** | `vitest` | `jest` | 快速 ESM 优先 |
| **Enterprise** | `vitest` + `playwright` + CI matrix | `jest` + `puppeteer` | E2E + 多 Node 版本 |

### 沙箱 (Sandbox)

> **何时读本节**：实现 Agent 工具执行隔离前读本节，并**以 `references/12-sandbox-advanced.md` 为事实源**。本表只做选型，隔离细节与实现约束以 12 为准。

| 级别 | 推荐 | 替代 | 说明 |
|---|---|---|---|
| **Minimal** | 路径白名单 / WASM 沙箱 (WASI) | — | 纯白名单，或将不可信逻辑编译为 wasm 指令级隔离（见 12）；**`vm2` 已弃用，禁止使用** |
| **Professional** | `isolated-vm` | `dockerode` | V8 隔离 + Docker（进程级隔离，见 12 Professional） |
| **Enterprise** | `isolated-vm` + 微 VM (Firecracker / microsandbox) | `dockerode` + gVisor | 多级隔离，零信任环境（见 12 Enterprise） |

> ⚠ **`vm2` 已于 2023 年 2 月被原作者标记为弃用且停止维护，存在已知逃逸 CVE**——已从本表移除，替换为「路径白名单 / WASM 沙箱」。选型须以 `references/12-sandbox-advanced.md` 为准。

### 监控 (Monitoring)

| 级别 | 推荐 | 替代 | 说明 |
|---|---|---|---|
| **Minimal** | 无 | — | — |
| **Professional** | `prom-client` | 自定义 | Prometheus 指标 |
| **Enterprise** | OpenTelemetry JS SDK + Grafana | Datadog | 全链路 |

### 配置管理

| 级别 | 推荐 | 替代 | 说明 |
|---|---|---|---|
| **Minimal** | `dotenv` | `process.env` | `.env` 加载 |
| **Professional** | `convict` | `config` | Schema 验证 |
| **Enterprise** | `convict` + 远程配置源 | `node-config` | 多源合并 |

### 数据库 (可选)

| 级别 | 推荐 | 替代 | 说明 |
|---|---|---|---|
| **Minimal** | 无 | — | 文件系统 |
| **Professional** | SQLite (`better-sqlite3`) | — | 同步高性能 |
| **Enterprise** | PostgreSQL (`pg` / `drizzle-orm`) | — | 生产级 |

---

## 2026 新增选型维度

> 下列维度为 v4 新增，覆盖「评测 / 追踪 / 模型路由」三类 Agent 生产化必需能力，均为**语言无关**选型，不区分 Python / Node 生态。沙箱维度见上文各生态的「沙箱 (Sandbox)」小节（已对齐 `references/12-sandbox-advanced.md`）。

### 评测框架 (Evaluation)

> **何时读本节**：Agent 已能跑通但你需要回答「它靠不靠谱、改一行会不会引入回归」时读本节，并对照 `references/15-evaluation.md`（评轨迹而非评答案、CI 门禁阈值、pass^k 可靠性指标）。

| 级别 | 推荐 | 替代 | 说明 |
|---|---|---|---|
| **Minimal** | 手工冒烟 | — | 5–10 条 happy + 少量 edge 场景，人工核对 `terminal_state`（见 15 §10） |
| **Professional** | `promptfoo` / `DeepEval` | 自研 yaml 断言 | 结构化用例 + `assert_trace`/`assert_final` + CI 门禁（见 15 §7 阈值） |
| **Enterprise** | `Inspect AI`（或同类）+ 自研 grader | `promptfoo` Enterprise + LLM-as-judge | 生产 1%–5% 采样回流 + 趋势告警 + 失败沉淀 golden set（见 15 §8/§11） |

选择依据：
- Minimal：原型期，用人工冒烟验证主路径即可
- Professional：需把评测纳入 CI，judge 一致率 ≥ 85% 后入门禁
- Enterprise：需生产回流闭环与多层 grader，安全类指标 `=0` 为硬门禁

### 追踪 / 可观测平台 (Observability / Tracing)

> **何时读本节**：上线后需要看「这个请求经历了什么、花了多少、有没有作恶」时读本节，并对照 `references/14-observability.md`（三支柱、质量指标、生产回流趋势告警）。

| 级别 | 推荐 | 替代 | 说明 |
|---|---|---|---|
| **Minimal** | 无 | — | 仅依赖 Agent 自身文本输出调试（见 14 Minimal） |
| **Professional** | `Langfuse` | `Weave` / `LangSmith` | LLM 专用追踪：token/成本分解、prompt 版本、评测关联（见 14 Trace 节） |
| **Enterprise** | `Langfuse` / `Braintrust` + OpenTelemetry | OTel Collector + Grafana | 全链路 Trace/Metrics/Logs 关联 + 质量指标面板 + 趋势告警（见 14 Enterprise） |

选择依据：
- Minimal：个人使用，无监控需求
- Professional：需要 LLM 调用级追踪与成本归因
- Enterprise：需要跨服务 Trace 关联、质量指标下钻与告警

### 模型路由 (Model Routing)

> **何时读本节**：需要把不同步骤路由到 cheap / strong 模型以控成本时读本节，并对照 `references/02-phase-llm.md` 的 `ModelRouter`（路由决策必须可审计）。

| 级别 | 推荐 | 替代 | 说明 |
|---|---|---|---|
| **Minimal** | 无 | — | 单供应商直接调用，无路由（见 02 Minimal） |
| **Professional** | 手写规则路由（基于 `ModelRouter`） | 配置化 cheap/strong 两档池 | 按步骤类型路由，`HARD_REASONING` 才走 strong，决策落审计（见 02 `ModelRouter`） |
| **Enterprise** | RouteLLM 类方案（学习式路由） | `ModelRouter` + 在线学习 | 前沿模型只留给难推理，报告约 95% 质量 / ~85% 降本，路由决策可审计（见 02） |

选择依据：
- Minimal：固定用一个模型，路由是过度工程
- Professional：规则即可覆盖绝大多数成本优化
- Enterprise：用量大、需自动化路由与成本归因

> 注：tool search（工具检索）属于工具系统范畴，选型见 `references/03-phase-tools.md`；不在本技术栈表重复列项。

---

## 决策规则 (Decision Rules)

构建 Agent 时，按以下优先级规则选择技术栈：

### 规则 1：规模优先原则
```
Minimal       → 标准库优先，0-2 个三方依赖，所有功能在单文件内
Professional  → 选择成熟稳定的库，5-8 个依赖，模块化组织
Enterprise    → 全套生态栈，10+ 个依赖，需考虑可观测性和运维
```

### 规则 2：一致性原则
- 同一项目中，所有模块应遵循同一级别
- 不允许 `Minimal` 级别的日志 + `Enterprise` 级别的验证混合
- 升级路径：应从 Minimal 平滑迁移到 Professional，不得跳级

### 规则 3：可替换原则
- 每个推荐都有一个备选方案
- 备选应在功能上等价，仅在实现风格上不同
- 当推荐库出现重大 Breaking Change 时，可快速切换到替代

### 规则 4：依赖收敛原则
- Professional 级别总依赖数应控制在 8 个以内
- Enterprise 级别总依赖数应控制在 20 个以内（含传递依赖优化）
- 每个依赖的选择需有明确理由（性能/生态/维护性）

---

## 反模式 (Anti-Patterns)

| 反模式 | 后果 | 正确做法 |
|---|---|---|
| Minimal 规模引入 `pydantic` | 过度工程，依赖膨胀 | 使用 `dataclasses` 或手动验证 |
| Professional 规模使用 `print()` | 缺乏结构化日志，调试困难 | 使用 `structlog` / `pino` |
| Enterprise 规模缺少 OpenTelemetry | 不可运维，故障定位困难 | 集成 OTel SDK |
| 跨层混用 (Mixed Tiers) | 代码风格不一致，维护成本高 | 统一技术栈层级 |
| 选择已弃用的库 | 安全漏洞，无上游支持 | 检查库的维护状态和社区活跃度 |
| 仅凭流行度选择 | 不符合实际需求 | 按决策规则评估匹配度 |
| 忽略生态兼容性 | 依赖冲突 (Diamond Dependency) | 检查传递依赖的版本约束 |

---

⚠ **AI 构建提示**：

```
当用户选择构建规模后，你应：

1. 识别规模标签 (Minimal / Professional / Enterprise)
2. 遍历上表中该规模对应的推荐项
3. 将推荐依赖写入 pyproject.toml 或 package.json
4. 仅在选择 Enterprise 时引入 OpenTelemetry 相关依赖
5. 仅在选择 Professional+ 时引入测试框架
6. 确保不引入属于更高规模层级的依赖（如 Minimal 不得有 pydantic）

检查清单：
□ 日志库与规模匹配
□ CLI 库与规模匹配
□ 验证库与规模匹配
□ 测试框架未在 Minimal 中引入
□ Enterprise 级别包含监控依赖
□ 所有推荐使用其最新稳定版本
□ 沙箱选型与 `references/12-sandbox-advanced.md` 一致（未另起隔离方案）
□ 评测 / 追踪 / 模型路由维度未在不匹配的规模引入
□ 所有推荐已检查维护状态（无 `vm2` 等已弃用项）
```

---

## 选型自检清单

> 完成任何技术栈选型后，逐条核对。任一项不通过即视为选型冒进，应回退或替换。

| # | 自检项 | 检查要点 | 不通过的处理 |
|---|---|---|---|
| 1 | **是否检查维护状态** | 每个推荐项过一遍「最近 release / issue 响应 / 已知 CVE / 官方推荐」四项判据；已弃用项（如 `vm2`）必须移除 | 降级或换用替代项；标「检查维护状态」 |
| 2 | **是否与规模匹配** | 推荐项级别与 Minimal/Professional/Enterprise 一致，不跨层混用（如 Minimal 不得引入 Enterprise 级依赖） | 回退到该规模应选项 |
| 3 | **是否引入不必要的企业级依赖** | Professional 依赖 ≤ 8、Enterprise ≤ 20；不因「将来可能用到」提前引入 OTel / 微 VM / 评测平台 | 砍掉非当前规模必需的依赖 |
| 4 | **是否有对应抽象接口可替换** | 每个推荐项都有等价替代（见各表「替代」列），且通过抽象接口（如 `ILLMClient`、`ModelRouter`）解耦，重大 Breaking Change 可快速切换 | 补抽象层或改选可替换方案 |

补充判据（与反模式表联动）：
- 「选择已弃用的库」→ 见清单第 1 项，必须检查维护状态。
- 「跨层混用」→ 见清单第 2 项，统一技术栈层级。
- 「仅凭流行度选择」→ 必须按本文件决策规则（规模优先 / 一致性 / 可替换 / 依赖收敛）评估匹配度。
- 沙箱维度必须与 `references/12-sandbox-advanced.md` 一致，不得另起隔离方案（见清单第 4 项「可替换」的边界：隔离事实源唯一）。