# 可观测性设计

> Observability = The ability to understand the internal state of a system from its external outputs.
> For Agent Harness: Traces show what happened, Metrics show how well, Logs show why.

---

## 三支柱架构

```
                    ┌───────────────────────────────────┐
                    │          Agent Harness             │
                    │                                    │
                    │  ┌─────────┐ ┌────────┐ ┌───────┐ │
                    │  │  Trace  │ │Metrics │ │ Logs  │ │
                    │  │ (链路)  │ │ (指标) │ │(日志) │ │
                    │  └────┬────┘ └───┬────┘ └───┬───┘ │
                    │       │          │          │      │
                    └───────┼──────────┼──────────┼──────┘
                            │          │          │
              ┌─────────────┼──────────┼──────────┼──────────────┐
              │             ▼          ▼          ▼              │
              │     ┌──────────┐ ┌──────────┐ ┌──────────┐      │
              │     │Langfuse  │ │Prometheus│ │  Loki /  │      │
              │     │(LLM 追踪)│ │(指标收集)│ │  ELK     │      │
              │     └──────────┘ └──────────┘ └──────────┘      │
              │                             │                    │
              │                        ┌────▼────┐              │
              │                        │ Grafana │              │
              │                        │(可视化) │              │
              │                        └─────────┘              │
              │              Observability Stack                │
              └────────────────────────────────────────────────┘
```

### 三支柱关系

| 支柱 | 回答的问题 | 数据粒度 | 保留周期 | Agent 独有挑战 |
|---|---|---|---|---|
| **Trace** | "这个请求经历了什么？" | 单次请求级 | 7-30天 | LLM 调用的 token/成本追踪 |
| **Metrics** | "系统整体健康吗？" | 聚合统计级 | 90-365天 | 工具调用成功率分解 |
| **Logs** | "具体发生了什么？" | 事件/消息级 | 7-90天 | 权限决策的审计记录 |

---

## Trace (链路追踪)

### Span 层级模型

```
Session Span (整个会话)
├── Turn Span #1 (第 1 轮)
│   ├── LLM Call Span (模型推理)
│   │   ├── Token Usage: {input: 1500, output: 300}
│   │   └── Cost: $0.003
│   ├── Tool Use Span: write_file (工具调用)
│   │   ├── Duration: 45ms
│   │   ├── Status: success
│   │   └── File: server.py (332 bytes)
│   ├── Permission Check Span (权限检查)
│   │   ├── Tool: write_file
│   │   └── Decision: allowed (by rule)
│   └── Tool Use Span: bash (工具调用)
│       ├── Duration: 2300ms
│       ├── Status: success
│       └── Command: pip install flask
├── Turn Span #2
│   └── ...
└── Session Summary
    ├── Total Turns: 5
    ├── Total Tokens: 12000
    └── Total Cost: $0.025
```

### OpenTelemetry Span 属性规范

| Span 类型 | 关键属性 | 示例值 |
|---|---|---|
| `agent.session` | `session.id`, `agent.model`, `agent.version` | `session-abc123`, `claude-4`, `1.2.0` |
| `agent.turn` | `turn.number`, `turn.reason` | `3`, `user_initiated` |
| `llm.call` | `llm.model`, `llm.temperature`, `llm.input_tokens`, `llm.output_tokens`, `llm.cost`, `llm.latency_ms` | `claude-4`, `0.7`, `1500`, `300`, `0.003`, `1200` |
| `tool.execute` | `tool.name`, `tool.status`, `tool.duration_ms`, `tool.error_type` | `write_file`, `success`, `45`, `null` |
| `permission.check` | `permission.tool`, `permission.path`, `permission.decision` | `write_file`, `/app/config.json`, `allowed` |
| `compaction` | `compaction.reason`, `compaction.messages_before`, `compaction.messages_after` | `context_limit`, `50`, `30` |

### Langfuse 集成 (LLM 专用追踪)

Langfuse 负责 LLM 调用级别的详细追踪，超越通用 OpenTelemetry 的能力：

| 追踪维度 | OpenTelemetry | Langfuse |
|---|---|---|
| Token 用量分解 (input/output) | ✅ | ✅ (自动捕获) |
| 每次调用的成本估算 | ❌ | ✅ (内置 pricing) |
| 缓存命中率 | ❌ | ✅ (Cache read/write tokens) |
| Prompt 版本追踪 | ❌ | ✅ (Prompt management) |
| 评测数据关联 | ❌ | ✅ (Datasets + Scores) |

---

## Metrics (指标)

### 7 项核心指标

#### 1. Token 消耗率

```
指标名称: agent_tokens_total
类型: Counter
标签 (Labels): {session_id, model, token_type: input|output}
导出频率: 每个 turn_end 时增量更新
用途: 成本预测、模型选择优化
```

#### 2. LLM 延迟

```
指标名称: agent_llm_latency_seconds
类型: Histogram
标签: {model, status: success|error}
Buckets: [0.1, 0.5, 1, 2, 5, 10, 30, 60, 120]
导出频率: 每次 LLM 调用完成
用途: SLO 监控、模型性能对比
告警阈值: p99 > 30s
```

#### 3. 工具调用成功率

```
指标名称: agent_tool_calls_total
类型: Counter (success + error 两个系列)
标签: {tool_name, status: success|error, error_type}
导出频率: 每次工具调用完成
用途: 工具稳定性分析、错误类型分布
告警阈值: success_rate < 90% (by tool_name) 持续 5 分钟
```

#### 4. 压缩频率

```
指标名称: agent_compactions_total
类型: Counter
标签: {reason: context_limit|cost_optimization|user_request}
导出频率: 每次压缩触发
用途: 上下文管理策略调整
告警阈值: > 10 次/分钟 (异常压缩风暴)
```

#### 5. 错误率

```
指标名称: agent_errors_total
类型: Counter
标签: {error_type: timeout|api_error|tool_error|permission_denied|unknown}
导出频率: 每次错误发生
用途: 系统健康度、错误趋势分析
告警阈值: 总错误率 > 5% 持续 5 分钟
```

#### 6. 会话时长

```
指标名称: agent_session_duration_seconds
类型: Histogram
标签: {status: completed|expired|error|cancelled}
Buckets: [30, 60, 120, 300, 600, 1800, 3600]
导出频率: 会话结束时
用途: 用户行为分析、资源规划
```

#### 7. 预估成本

```
指标名称: agent_estimated_cost_dollars_total
类型: Counter
标签: {model, session_id}
导出频率: 每个 turn_end 时更新
用途: 成本归因、按模型/用户分析
计算: 基于模型的公开定价 (input_tokens * price_in + output_tokens * price_out)
```

### 质量指标层（v4 新增）

> 共识：Agent 可观测性已从"性能/成本"扩展到三层——**任务完成（Task Completion）/ 轨迹质量（Trajectory Quality）/ 安全合规（Safety & Compliance）**。性能与成本指标（上一节）只能回答"系统有没有坏"，质量指标回答"系统做得对不对、安全不安全"。

**何时读本节**：当你发现"延迟正常、错误率为零、成本也在预算内，但用户仍在抱怨 Agent 答非所问"时，说明你只有性能可观测、没有质量可观测。本节定义生产环境必须采集的质量指标。

#### 三层质量指标映射

| 层级 | 回答的问题 | 本层指标 |
|---|---|---|
| 任务完成 | 任务最终做完了吗？花了多少？ | `cost_per_task`、`steps_per_task`、`error_recovery_rate`、`escalation_rate` |
| 轨迹质量 | 过程走对了路吗？有没有绕、有没有卡？ | `tool_selection_accuracy`、`loop_detection_count` |
| 安全合规 | 有没有做违规的事 / 被攻陷？ | `policy_violation_rate`、`injection_resistance` |

#### 质量指标定义（8 项）

```
指标名称: agent_tool_selection_accuracy
层级: 轨迹质量
类型: Gauge (滑动窗口均值)
定义: 模型在每一步"该调用哪个工具"的决策正确的比例
计算口径: 正确决策数 / 总工具决策数。
         判定"正确"需 judge（LLM-as-judge 或规则校验）：该步是否应调用此工具、参数是否匹配意图。
标签: {model, tool_name}
告警: 周环比下降 > 20% 触发（见"生产回流"趋势告警，按相对基线而非绝对阈值）
```

```
指标名称: agent_steps_per_task
层级: 任务完成
类型: Histogram
定义: 单个任务从开始到结束平均执行的步数（1 step = 1 次 LLM 决策 + 1 次执行）
计算口径: 总 step 数 / 已完成任务数
Buckets: [1, 3, 5, 8, 12, 20, 40]
用途: 步数激增 = 绕路/循环前兆；骤降 = 过早放弃
告警: 周环比 > 30% 移动触发
```

```
指标名称: agent_loop_detection_count
层级: 轨迹质量
类型: Counter
定义: 单位时间内被检测到"重复/无有效进展"的轨迹数
计算口径: 同一 session 内连续 N 步语义相似度 > 阈值或相同动作重复，计 1 次
标签: {loop_kind: semantic_repeat|identical_action|no_progress}
用途: 循环工程有效性验证、max_iterations 调参
```

```
指标名称: agent_error_recovery_rate
层级: 任务完成
类型: Gauge
定义: 遇到错误但最终仍成功的任务比例
计算口径: 遇到 >=1 次错误的任务中，最终 status=completed 的数量 / 遇到错误的任务数
用途: 韧性评估；硬故障立竿见影，但恢复率慢漂移只能靠趋势抓（见"生产回流"）
```

```
指标名称: agent_policy_violation_rate
层级: 安全合规
类型: Gauge
定义: 策略约束被触碰/违反的决策比例
计算口径: 触发 BLOCK 级规则或 strategy 约束被违反的次数 / 总决策数
标签: {policy_id, severity}
用途: 安全兜底有效性（与 references/06-phase-permissions.md 联动）
告警: 任何 > 0 的 BLOCK 级违规都应升级（绝对阈值 = 0，安全项不趋势化）
```

```
指标名称: agent_injection_resistance
层级: 安全合规
类型: Gauge
定义: 对抗用例（prompt injection）通过率
计算口径: 通过注入测试的用例数 / 总对抗用例数
来源: 对抗用例沉淀自生产失败（见"生产回流" + references/15-evaluation.md）
注意: 这是离线/评测集指标，生产侧以 policy_violation_rate 近似监控
```

```
指标名称: agent_escalation_rate
层级: 任务完成
类型: Gauge
定义: 升级到人工的任务比例
计算口径: status=escalated 的任务数 / 总任务数
标签: {escalation_reason}
告警: 周环比 > 20% 移动 = 真信号；4.1%→4.3% 是噪声，勿按绝对阈值告警
```

```
指标名称: agent_cost_per_task
层级: 任务完成
类型: Histogram
定义: 单个任务的端到端成本（非累计、非单 turn）
计算口径: sum(该 session 内所有 LLM 调用的 input*price_in + output*price_out)
          + 外部工具成本（若有按次计费）
          + 人工升级成本分摊（optional）
        再对已完成任务取分布
Buckets: [0.01, 0.05, 0.1, 0.5, 1, 5, 20]
与 agent_estimated_cost_dollars_total 的区别: 后者是 Counter（全局累计），
        本指标是任务级均值/分布，用于"每个任务花多少"而非"总共花多少"
告警: 相对 trailing baseline 周环比 > 25% 触发（不是绝对 threshold）
```

#### 质量指标三档差异表

| 规模 | 采集的质量指标 | 计算方式 |
|---|---|---|
| **Minimal** | 不采集 | — |
| **Professional** | `cost_per_task`、`steps_per_task` | 同步简单统计（Histogram/Counter） |
| **Enterprise** | 全 8 项 | 异步 judge + 三层质量面板（Grafana） |

**AI 构建提示**：质量指标多数依赖异步 judge（见"生产回流"），不需要每次调用实时计算。Minimal 不采集；Professional 仅采 `cost_per_task` + `steps_per_task`；Enterprise 全量采集并展示三层质量面板。安全合规层指标（`policy_violation_rate`、`injection_resistance`）的告警方向由 `references/06-phase-permissions.md` 的 Budget/策略定义派生。

### Prometheus 导出端点

```
GET /metrics

输出格式:
# HELP agent_tokens_total Total tokens consumed
# TYPE agent_tokens_total counter
agent_tokens_total{session_id="abc123",model="claude-4",token_type="input"} 15000
agent_tokens_total{session_id="abc123",model="claude-4",token_type="output"} 3200
# HELP agent_llm_latency_seconds LLM call latency
# TYPE agent_llm_latency_seconds histogram
agent_llm_latency_seconds_bucket{model="claude-4",le="1"} 150
agent_llm_latency_seconds_bucket{model="claude-4",le="2"} 230
...
```

---

## Logs (日志)

### 结构化日志 Schema

```json
{
  "timestamp": "2025-01-15T10:30:02.350Z",
  "level": "INFO",
  "logger": "agent_harness.session",
  "event": "tool_result_received",
  "trace_id": "a1b2c3d4e5f6...",
  "session_id": "sess-abc123",
  "turn_number": 3,
  "context": {
    "tool_name": "write_file",
    "success": true,
    "duration_ms": 45,
    "file_size_bytes": 332
  }
}
```

### 日志级别使用规范

| 级别 | 含义 | 使用场景 | 环境 |
|---|---|---|---|
| **DEBUG** | 开发调试信息 | 工具调用参数的**字段名与长度（不含值）**、沙箱配置维度、Span 调试元数据 | 开发环境（仍受"日志脱敏规则"约束，禁止记录 prompt 全文与入参原文） |
| **INFO** | 正常操作记录 | Turn 开始/结束、工具执行结果、权限检查通过 | 所有环境 |
| **WARN** | 需要关注但不影响功能 | 权限被拒绝、工具调用超时重试、压缩频繁触发、接近速率限制 | Staging + 生产 |
| **ERROR** | 功能异常 | 工具调用失败、LLM API 错误、沙箱崩溃、会话恢复失败 | 所有环境 |

### Context Binding (上下文绑定)

所有日志必须包含以下上下文字段（通过 `structlog.bind()` 或 `logger.child()` 实现）：

| 字段 | 来源 | 链路能力 |
|---|---|---|
| `trace_id` | 从 OpenTelemetry context 提取 | 关联 Trace |
| `session_id` | Session 对象 | 关联同一会话的所有日志 |
| `turn_number` | Session turn 计数器 | 定位具体轮次 |
| `model` (条件) | LLM 调用上下文 | 定位模型相关问题 |

### 日志脱敏规则（v4 新增）

**何时读本节**：在配置任何结构化日志前。Agent 日志极易误记 prompt 全文与工具入参，造成数据泄露与合规风险——这是上线前的硬门槛。

**默认禁止记录的字段**（任何环境、任何级别均不记录）：

| 禁止字段 | 风险 |
|---|---|
| prompt / LLM 输入全文 | 可能含用户 PII、商业机密 |
| 工具入参原文（arguments 全文） | 可能含密钥、路径、敏感数据 |
| 凭证 / secret / token / API key | 直接泄露凭据 |
| 文件内容正文 | 可能含源码机密、用户数据 |

> 即使在 DEBUG 级别，也**不得**记录上述字段。上表"日志级别使用规范"中旧版"DEBUG 记录 LLM prompt 全文、工具调用参数详情"已被本规则废止——DEBUG 仅允许记录字段名与长度，不允许记录值。

**允许记录的字段白名单**：

| 字段 | 说明 | 示例 |
|---|---|---|
| `session_id` | 会话标识 | `sess-abc123` |
| `turn_index` | 轮次序号 | `3` |
| `tool_name` | 工具名（不含参数） | `write_file` |
| `tool_status` | 工具结果状态 | `success` / `error` |
| `error_kind` | 错误类型（不含堆栈中的敏感值） | `timeout` |
| `latency_ms` | 耗时 | `2300` |
| `token_count` | token 数（不含文本） | `12000` |
| `cost_usd` | 成本（不含计费密钥） | `0.025` |
| `loop_kind` | 循环类型 | `semantic_repeat` |
| `policy_id` | 触发的策略 ID（不含规则正文） | `P-07` |

**日志脱敏三档差异表**：

| 规模 | 脱敏实现 |
|---|---|
| **Minimal** | 不记录任何日志，自然满足白名单 |
| **Professional** | 结构化日志 + 白名单字段过滤（记录前裁剪禁止字段） |
| **Enterprise** | 白名单过滤 + 集中脱敏网关 + 审计留痕 |

**AI 构建提示**：实现一个 `redact(event)` 函数，在 `logger.info(...)` 前强制只保留白名单字段、丢弃禁止字段；任何新增日志字段都必须先在白名单登记，未经登记默认不记录。生产 trace 导出为评测用例（见"生产回流"）前必须先过此脱敏。

---

## Session = 审计日志

Session 的 append-only 事件日志天然就是审计日志。无需为 Agent 操作建立独立的审计系统。

### 审计就绪矩阵

| 审计需求 | Session 事件日志覆盖 | 额外配置需求 |
|---|---|---|
| 操作时间线 | `timestamp` 字段 | 无 |
| 操作者身份 | `role: "user"` + Session 关联的用户 ID | 需在 Session 创建时绑定用户 |
| 工具调用记录 | `tool_use` + `tool_result` | 无 |
| 权限决策 | `permission.check` 事件 | 需在 Permission 模块中发射事件 |
| 数据访问记录 | `tool_use` 的 `tool_name=read` | 无 |
| 数据修改记录 | `tool_use` 的 `tool_name=edit` + `arguments` | 无 |
| 异常事件 | `tool_result.success=false` | 无 |
| 成本核算 | `turn_end.token_summary.total_cost` | 模型 pricing 表 |

---

## 告警规则 (Enterprise 级别)

| 告警名称 | 条件 | 严重级别 | 建议响应 |
|---|---|---|---|
| 高错误率 | `rate(agent_errors_total[5m]) / rate(agent_tool_calls_total[5m]) > 0.05` | Critical | 暂停 Agent 自动审批，切换人工审核 |
| LLM 高延迟 | `histogram_quantile(0.99, agent_llm_latency_seconds) > 30` | Warning | 检查 API 状态页，考虑降级到更快模型 |
| 压缩风暴 | `rate(agent_compactions_total[1m]) > 10` | Warning | 检查上下文大小配置，可能需增大 context window |
| 工具调用异常 | `rate(agent_tool_calls_total{status="error"}[5m]) > 0.1 * rate(agent_tool_calls_total[5m])` | Critical | 检查具体工具的错误分布，可能需回滚工具变更 |
| 成本异常 | `rate(agent_estimated_cost_dollars_total[1h]) > budget.hourly_limit`（权威定义在 references/06-phase-permissions.md 的 Budget，本文件不重定义该值） | Warning | 检查是否有 Agent 进入无限循环，需人工介入 |
| 会话积压 | `agent_active_sessions > max_concurrent * 0.8` | Warning | 扩容 Harness 实例或限流新会话 |

---

## 生产回流与趋势告警（v4 新增）

**何时读本节**：当你的质量指标只在离线评测里好看、线上却持续劣化却无人察觉时。本节定义如何把线上生产数据抽样回流成评测信号，并只靠"趋势"而非"绝对阈值"抓慢漂移。

### 为什么必须趋势化

> 技术依据：硬故障立竿见影，慢漂移只能靠趋势抓。例：工具选择准确率从 92% 掉到 78%，单看每天都"正常"，只有周环比趋势能暴露。
> 按绝对阈值告警的团队，最终都会把告警频道 mute 掉——因为 4.1% 升到 4.3% 这种噪声会淹没真信号。真信号是**周环比 20% 的升级率移动**。

### 生产采样回流

```
采样率: 生产流量 1-5%（默认 2%）
抽样方式: 按 session_id 哈希分流，保证同一任务轨迹完整入样
judge: 与生产评测使用**同一个 judge**（LLM-as-judge 或规则），避免线上线下口径不一致
评分时机: 异步、离线批处理，不阻塞主链路
看什么: 分布漂移（drift），不是绝对分数。
        一个任务 0.91 分没有意义，分布从 [0.95,0.97] 漂到 [0.80,0.85] 才有意义
```

### 趋势告警规则（相对 trailing baseline）

```
原则: 所有质量/成本告警以 trailing baseline（近 7 天滚动窗口）为基准，超相对变化才告警

agent_escalation_rate:     周环比 > 20% 且绝对量 >= 5 例  → Warning
agent_tool_selection_accuracy: 周环比 < -20%             → Critical
agent_steps_per_task:      周环比 > 30%                  → Warning
agent_cost_per_task:       周环比 > 25%                  → Warning
agent_policy_violation_rate: 任何 BLOCK 级违规 (绝对 = 0) → Critical（安全项例外，不趋势化）

# 伪 PromQL：告警方向由基线派生，非写死阈值
rate(agent_escalation_rate) > 1.2 * baseline(agent_escalation_rate, 7d)
```

### 失败沉淀为 golden set

```
闭环: 每条生产失败（status=error|escalated|policy_violation）必须沉淀为一条 golden set 用例
去向: references/15-evaluation.md 定义的评测集（回归 + 对抗）
目的: 防止同类失败复发；injection_resistance 的对抗用例即来源于此
```

### 与 references/15-evaluation.md 打通

| 流向 | 说明 | 实现 |
|---|---|---|
| 评测 → 面板 | 评测结果（score / 分层）回灌可观测面板，与线上质量指标同屏对比 | Langfuse Scores → Grafana annotation |
| trace → 用例 | 任意生产 trace 可一键导出为评测用例（保留 session_id / tool_name / error_kind，脱敏后） | "Export as eval case" 按钮 |
| 用例 → 回流 | golden set 用例随生产采样共同进入 judge，构成回归基线 | 见上"失败沉淀" |

### 生产回流三档差异表

| 规模 | 采样回流 | judge | 趋势告警 |
|---|---|---|---|
| **Minimal** | 否 | — | — |
| **Professional** | 否（仅离线评测，参照 references/15-evaluation.md） | 离线批处理 | 仅 `cost_per_task` 周环比 |
| **Enterprise** | 1-5% 生产采样 | 同一 judge 异步 | 全量相对基线 |

**AI 构建提示**：生产回流的所有 judge 调用必须异步，绝不能阻塞用户主链路；回流入样的 trace 导出为评测用例前必须先走"日志脱敏规则"白名单过滤。

---

## 规模特定实现概要

### Minimal (~0 行)
```
无可观测性基础设施。
依赖 Agent 自身输出的文本作为调试依据。
仅适用于个人使用或一次性脚本。
```

### Professional (~100 行)
```
核心组件：
  - StructuredLogger: structlog (Python) / pino (Node)
  - BasicMetrics: Counter + Histogram (基于 prometheus-client)

实现要点：
  - 日志输出为 JSON 格式到 stdout/stderr
  - metrics 通过 /metrics 端点导出
  - trace_id 通过 contextvars 或 AsyncLocalStorage 传递
  - 不含 Grafana/Langfuse 集成
```

### Enterprise (~400 行)
```
核心组件：
  - OpenTelemetry SDK (自动插桩 + 手动 Span)
  - Prometheus + Grafana (指标采集 + 可视化)
  - Langfuse (LLM 专用追踪 + 成本分析)
  - Alertmanager (告警路由)

实现要点：
  - 配置 OTLP Exporter 指向 Collector
  - 在关键路径手动创建 Span (LLM call, tool execution, permission check)
  - 配置 Span → Log 关联 (注入 trace_id)
  - 配置 Grafana Dashboard (导入预定义 JSON 模板)
  - 配置告警规则文件 (.yml) 并加载到 Prometheus
  - 配置 Langfuse callback 拦截 LLM SDK 调用
```

---

⚠ **AI 构建提示**：

```
根据用户选择的规模实现可观测性：

Minimal 级别：
  跳过。不添加任何可观测性代码。

Professional 级别：
  1. 安装 structlog (Python) 或 pino (Node)
  2. 在入口处配置 JSON 格式输出
  3. 在所有关键事件处添加 logger.info(event="event_name", **context)
  4. 安装 prometheus-client (Python) 或 prom-client (Node)
  5. 添加 Counter: agent_tool_calls_total, agent_errors_total
  6. 添加 Histogram: agent_llm_latency_seconds
  7. 注册 /metrics HTTP 端点

Enterprise 级别：
  1. 安装 opentelemetry-api, opentelemetry-sdk, opentelemetry-exporter-otlp
  2. 配置 TracerProvider 和 OTLP Exporter
  3. 在所有工具调用包装器中创建 Span
  4. 安装 langfuse SDK 并配置 callback
  5. 在 LLM 调用处标记为 Langfuse Generation
  6. 导入 Grafana Dashboard JSON
  7. 配置 Prometheus 告警规则文件

检查清单：
  □ 每个 Span 包含必需的属性 (session_id, turn_number, etc.)
  □ 每行日志包含 trace_id 和 session_id
  □ /metrics 端点可被 Prometheus 抓取
  □ 告警规则配置文件格式正确
  □ Langfuse 回调不阻塞主流程 (异步发送)
```

---

# 动态断点注入与热修改策略 (v4)

> 配合 Phase 4 的 Loop Engineering 升级，引入运行时动态断点和热修改能力，使运维人员可以在不下线 Agent 的情况下注入审批、调整参数。

## 设计原理

生产环境中的 Agent Loop 不能是一个黑箱。通过全链路 tracing 实时监控循环状态，运维人员可以在运行时：
- **动态断点注入**：看到某个 Agent 即将执行高风险操作，通过管理面板挂入人工审批
- **热修改策略**：在不下线 Agent 的情况下调整循环参数（max_iterations、temperature 等）

## 抽象接口

```python
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass


@dataclass
class Breakpoint:
    """动态断点定义"""
    id: str
    condition: Callable[[Dict], bool]  # 触发条件函数
    action: str                        # 触发后动作
    reason: str                        # 注入原因
    created_by: str                    # 操作者
    created_at: str                    # 创建时间
    kind: str = "approval"             # "approval" 审批类 | "block" 阻断类（v4 修正，见下文语义）


class BreakpointManager:
    """动态断点管理：运维人员可在运行时注入/移除断点"""

    def __init__(self):
        self._breakpoints: Dict[str, Breakpoint] = {}

    def inject(self, bp: Breakpoint) -> None:
        """注入断点：挂载到 Agent 循环的下一步"""
        ...

    def remove(self, bp_id: str) -> None:
        """移除断点：恢复自动执行"""
        ...

    def list_active(self) -> List[Breakpoint]:
        """列出当前激活的断点"""
        ...


class HotConfigSource:
    """热修改配置源：从配置中心实时拉取参数，无需重启"""

    def __init__(self, config_center_url: str):
        self._url = config_center_url
        self._watchers: Dict[str, Callable] = {}

    async def get(self) -> Dict[str, Any]:
        """获取当前最新配置"""
        ...

    def watch(self, key: str, callback: Callable) -> None:
        """监听配置变更"""
        ...


class ObservableLoop:
    """
    可观测循环：每个节点都被追踪，运维人员可在管理面板看到实时状态并注入断点。
    """

    def __init__(self, config: Dict, breakpoint_manager: BreakpointManager, hot_config: HotConfigSource):
        self.config = config
        self.breakpoint_manager = breakpoint_manager
        self.hot_config = hot_config

    async def run(self, task: str) -> AsyncGenerator[AgentEvent, None]:
        """主循环 —— 每轮检查断点和热修改"""
        state = {"task": task, "iteration": 0}
        while state["iteration"] < self.config["max_iterations"]:
            # 1. 检查是否有运维注入的断点
            breakpoint = await self._check_breakpoint(state)
            if breakpoint:
                approval = await self._request_human_approval(breakpoint)
                if not approval["approved"]:
                    state["status"] = "paused_by_human"
                    return

            # 2. 检查热修改
            new_config = await self.hot_config.get()
            if new_config != self.config:
                self.config = new_config

            # 3. 执行一步
            yield await self._execute_step(state)
            state["iteration"] += 1

    async def _check_breakpoint(self, state: Dict) -> Optional[Breakpoint]:
        """检查当前状态是否匹配任何激活的断点"""
        ...

    async def _request_human_approval(self, bp: Breakpoint) -> Dict:
        """向管理面板发送人工审批请求，等待响应（带超时）。

        超时行为由 bp.kind 决定（v4 修正）：
          - "approval" 审批类：超时自动放行，避免阻塞（记录审计日志）
          - "block"   阻断类：超时保持阻断并升级告警，绝不自动放行
        """
        ...

### 断点语义：审批类 vs 阻断类（v4 修正）

> 已拍板的安全保守方向：BLOCK 级规则的兜底不能在"审批超时"时失效。"超时自动放行"只适用于审批类，不适用于阻断类。

```
审批类 (approval)                阻断类 (block)
┌──────────────────┐           ┌──────────────────────┐
│ 超时 → 自动放行   │           │ 超时 → 保持阻断        │
│ 记录审计日志      │           │        + 升级告警       │
│ 用于人工复核      │           │ 用于安全兜底           │
│ 非危险操作        │           │ BLOCK 级规则 / 高危操作 │
└──────────────────┘           └──────────────────────┘
```

| 维度 | 审批类 approval | 阻断类 block |
|---|---|---|
| 适用场景 | 人工复核非危险操作 | BLOCK 级安全规则、高危写操作 |
| 超时（默认 300s） | **自动放行**（避免死锁） | **保持阻断 + 升级告警**（兜底不失效） |
| 审计要求 | 记录"超时放行"事件 | 记录"超时阻断+升级"事件 |
| 关联规则 | references/06-phase-permissions.md 的审批类 | 同文件 BLOCK 级规则 |

**断点语义三档差异表**：

| 规模 | 断点支持 |
|---|---|
| **Minimal** | 不使用断点 |
| **Professional** | 仅审批类（同步确认，超时放行） |
| **Enterprise** | 审批类 + 阻断类（阻断类超时升级告警） |

**AI 构建提示**：实现 `_request_human_approval` 时，先读 `bp.kind` 再决定超时策略；阻断类超时必须调用告警升级通道（而非返回 approved=True），这正是安全兜底的失效点，绝不可"为防死锁而放行"。

## 管理面板能力清单

| 能力 | 说明 | 实现方式 |
|------|------|---------|
| **实时火焰图** | 每个节点的耗时占比 | LangSmith Trace View / Weave |
| **动态断点** | 在下一步挂起，等待人工确认 | WebSocket + Redis 断点配置 |
| **热修改参数** | 修改 max_iterations / temperature | 配置中心（etcd / Consul）实时推送 |
| **成本仪表盘** | 实时 Token 消耗 + 预算预警 | Weave / LangSmith dashboards |
| **回放与调试** | 对历史轨迹逐步回放 | Temporal Replay / LangSmith Playground |
| **策略 A/B** | 同时运行多个策略版本对比 | 基于 trace tag 分流 |

## 规模适配

- **Minimal**：不使用可观测断点。
- **Professional**：基础结构化日志 + 指标计数器。
- **Enterprise**：完整可观测循环（动态断点 + 热修改 + 管理面板 + 策略 A/B）。

## AI 构建提示

```
根据用户选择的规模实现可观测断点：

Enterprise 级别：
  1. 实现 BreakpointManager 类，支持注入/移除/列出激活断点
  2. 实现 ObservableLoop 类，在每轮循环中检查断点和热修改
  3. 实现 HotConfigSource 类，从 etcd/Consul/Redis 拉取配置
  4. 实现 WebSocket 通道，用于管理面板与 Agent 的实时通信
  5. 实现 _request_human_approval 方法，支持超时（默认 300s）

关键约束：
  □ 断点检查不得阻塞主循环超过 10ms（异步检查 Redis/配置中心）
  □ 人工审批超时策略由 bp.kind 决定（v4 修正）：
      - 审批类 (approval)：超时自动放行，但记录审计日志（避免死锁）
      - 阻断类 (block)：超时保持阻断并升级告警，绝不自动放行（否则安全兜底失效）
  □ 热修改变更必须记录在 WAL 中（type: CONFIG_CHANGE）
  □ 断点配置持久化到 Redis，防止管理面板重启后丢失
  □ 策略 A/B 分流基于 trace tag，不影响主循环逻辑
```