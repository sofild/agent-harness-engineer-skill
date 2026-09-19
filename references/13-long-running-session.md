# 长时运行与跨会话交接 (v4)

> 本文件分两层：
> - **进程内层（In-Process Layer）**：WAL + 检查点，解决"单次进程崩溃后如何恢复"。
> - **跨会话层（Cross-Session Layer）**：handoff 文件 + feature list，解决"全新会话如何从零恢复任务意图"。
>
> 两层互补：进程内层让你"不丢状态"，跨会话层让你"换一个脑子也能接手"。

---

# 第一部分：进程内层（In-Process Layer）

> 以下章节从 v3 原 `13-session-design.md` 完整保留，作为进程内崩溃恢复的基础。
> 它们保证：**同一个进程（或同一份 WAL + 检查点）内，崩溃后可以精确重放恢复。**

## 会话设计：WAL 事件日志模式

> Session = Write-Ahead Log (WAL)
> 与数据库的 WAL 设计模式同源：Append-only、Immutable、Replayable、Single Source of Truth.

---

## 设计理念

### 为什么是 WAL？

传统的 Session 设计将"当前状态"存储在可变数据结构中，每次操作原地修改。问题：
- 无法回放历史 → 难以调试
- 崩溃时状态丢失 → 无法恢复
- 审计信息不完整 → 合规困难

WAL 模式将每次事件作为不可变记录追加写入，Session 状态 = WAL 的重放结果。

```
传统模式:  State { messages: [...], tools: [...] }  → 原地修改
WAL 模式:  Event log → 重放 → 构建 State
```

### 核心属性

| 属性 | 含义 | 实现方式 |
|---|---|---|
| **Append-only** | 不修改历史，只追加新事件 | JSONL 格式，逐行追加 |
| **Immutable** | 已写入的事件不可更改 | 文件权限 + 校验和 |
| **Replayable** | 可从头重放恢复状态 | 事件幂等设计 |
| **Single Source of Truth** | 所有组件从事件日志派生状态 | 无独立状态存储 |

---

## 5 种事件类型

### 事件分类

```
                    ┌─────────────────────┐
                    │     Session 事件     │
                    └──────────┬──────────┘
          ┌────────────┬──────┴──────┬────────────┐
          │            │             │            │
    用户侧事件    模型侧事件    工具侧事件    控制事件
          │            │             │            │
   user_message  assistant_text  tool_use     turn_start
                               tool_result   turn_end
```

### 事件 Schema

| 事件类型 | 必填字段 | 说明 |
|---|---|---|
| `user_message` | `{timestamp, uuid, content, role}` | 用户输入，role 固定为 "user" |
| `assistant_text` | `{timestamp, uuid, content, model, token_count}` | 模型生成的文本片段 |
| `tool_use` | `{timestamp, uuid, tool_name, arguments, parent_message_uuid}` | 工具调用声明 |
| `tool_result` | `{timestamp, uuid, success, output/error, tool_use_uuid}` | 工具执行结果 |
| `turn_start` | `{timestamp, uuid, turn_number, reason}` | turn 开始标记 |
| `turn_end` | `{timestamp, uuid, turn_number, reason, token_summary}` | turn 结束标记 |

其中 `reason` 字段枚举值：
- `complete`：正常完成
- `timeout`：超时中断
- `error`：异常错误
- `user_interrupt`：用户手动停止
- `compaction_trigger`：触发压缩

---

## 状态机 (State Machine)

```
                    ┌──────────┐
         创建 ─────→│   idle   │
                    └────┬─────┘
                         │ user_message 到达
                         ▼
                    ┌──────────┐
                    │ running  │←───── 多轮 tool_use/tool_result 循环
                    └────┬─────┘
              ┌─────┬────┴────┬──────┐
              │     │         │      │
          正常完成  超时     错误   暂停
              │     │         │      │
              ▼     ▼         ▼      ▼
           idle  expired    error  paused
             │
             │ 新消息到达
             ▼
          running (继续)
```

### 状态转换规则

| 当前状态 | 触发事件 | 新状态 | 条件 |
|---|---|---|---|
| `idle` | `user_message` | `running` | 无活跃 turn |
| `running` | `turn_end(reason=complete)` | `idle` | 模型返回最终响应 |
| `running` | `turn_end(reason=timeout)` | `expired` | 超过 turn 超时限制 |
| `running` | `turn_end(reason=error)` | `error` | 执行异常 |
| `running` | `pause_command` | `paused` | 用户手动暂停 |
| `paused` | `resume_command` | `running` | 用户手动恢复 |
| `expired` | 任何事件 | `expired` | 不可恢复，需新建会话 |
| `error` | `retry_command` | `running` | 从最后一个 turn_end 恢复 |

---

## JSONL 格式规范

### 格式定义

每行一个 JSON 对象，行与行之间以 `\n` 分隔。

```jsonl
{"type":"turn_start","timestamp":"2025-01-15T10:30:00.001Z","uuid":"a1b2...","turn_number":1,"reason":"user_initiated"}
{"type":"user_message","timestamp":"2025-01-15T10:30:00.002Z","uuid":"c3d4...","content":"创建一个 Python HTTP 服务","role":"user"}
{"type":"tool_use","timestamp":"2025-01-15T10:30:02.100Z","uuid":"e5f6...","tool_name":"write","arguments":{"path":"server.py","content":"..."},"parent_message_uuid":"g7h8..."}
{"type":"tool_result","timestamp":"2025-01-15T10:30:02.350Z","uuid":"i9j0...","success":true,"output":"File written: server.py","tool_use_uuid":"e5f6..."}
{"type":"assistant_text","timestamp":"2025-01-15T10:30:03.000Z","uuid":"k1l2...","content":"已创建 server.py...","model":"claude-4","token_count":{"input":150,"output":80}}
{"type":"turn_end","timestamp":"2025-01-15T10:30:03.001Z","uuid":"m3n4...","turn_number":1,"reason":"complete","token_summary":{"total_input":150,"total_output":80,"total_cost":0.003}}
```

### JSONL 的优势

| 特性 | JSONL | Binary Format | 关系数据库 |
|---|---|---|---|
| **追加友好** | ✅ 直接追加 | 需序列化 | 需 INSERT |
| **人类可读** | ✅ | ❌ | 部分 |
| **流式处理** | ✅ 逐行读取 | 需解码器 | 需游标 |
| **jq 可查询** | ✅ `jq 'select(.type=="tool_use")'` | ❌ | 需 SQL |
| **版本兼容** | ✅ 向前兼容 | 需版本协商 | Schema 迁移 |
| **存储效率** | 中等 | 高 | 高 |

---

## 重放与恢复

### 故障恢复流程

```
恢复入口: Harness 启动时检测到未完成的 Session

Step 1: 加载 Session 的 JSONL 文件
Step 2: 逐行重放到最后一个 turn_end
Step 3: 检查最后一个 turn_end.reason
  ├─ complete → Session 已完成，无需恢复
  ├─ timeout  → 从下一 turn 继续（原 turn 结果可能部分可用）
  ├─ error    → 通知用户选择 retry 或 abandon
  └─ (无 turn_end) → 最后一个 turn 未完成，重新执行
Step 4: 恢复后的 Harness 从 idle 状态开始接受新消息
```

### 负载迁移流程

```
迁移入口: 将 Session 从 Harness A 迁移到 Harness B

Step 1: Harness A 序列化：将整个 JSONL 文件作为迁移载荷
Step 2: 传输到目标 Harness B (通过共享存储或网络)
Step 3: Harness B 加载 + 重放 JSONL
Step 4: 验证重放后的状态与 Harness A 一致
Step 5: Harness A 标记为 migrated，拒绝后续请求
Step 6: Harness B 接管所有后续交互
```

### 调试重放

```
调试入口: 生产环境 Session 出现异常行为

Step 1: 导出生产 Session 的 JSONL 文件
Step 2: 在开发环境加载并重放
Step 3: 在关键事件处设置断点（turn_end、tool_use）
Step 4: 注入相同模型版本和参数
Step 5: 比较开发环境输出与生产输出
Step 6: 定位差异点 → 根因分析
```

---

## 双重超时机制

### Turn-level Timeout

| 参数 | 默认值 | 说明 |
|---|---|---|
| `turn_timeout` | 120s | 单轮最大执行时长 |
| `tool_timeout` | 30s | 单次工具调用最大时长 |
| `max_tool_calls_per_turn` | 25 | 单轮最大工具调用次数 |

超时行为：
- `turn_timeout` 触发 → 中断当前执行，记录 `turn_end(reason=timeout)`
- `tool_timeout` 触发 → 中断当前工具调用，返回 error result，继续 turn
- `max_tool_calls` 触发 → 强制完成 turn，发送用户消息通知

### Session-level Timeout

| 参数 | 默认值 | 说明 |
|---|---|---|
| `session_idle_timeout` | 600s | idle 状态最大等待时长 |
| `session_max_duration` | 3600s | 总会话最大时长 |

超时行为：
- `session_idle_timeout` 触发 → 状态切换为 expired，释放资源
- `session_max_duration` 触发 → 强制结束，发送用户消息通知，释放资源

---

## Session = 审计日志

WAL 模式的一个自然产物：Session 的事件日志本身就是完整的审计日志。

### 审计能力

| 审计需求 | 实现方式 |
|---|---|---|
| 谁在何时使用了什么工具 | `tool_use` 事件包含时间戳 + 工具名 |
| 每一轮模型返回了什么 | `assistant_text` 事件包含内容 + token |
| 哪些权限决策被做出 | 权限检查事件 (作为 tool_use 的子类型) |
| 操作是否成功 | `tool_result.success` 字段 |
| 错误发生的上下文 | `tool_result.error` + 前后的事件序列 |
| 会话的总成本 | 所有 `turn_end.token_summary` 累加 |

### 合规优势

- 完整：无遗漏，所有操作都记录在事件流中
- 不可篡改：Append-only + 校验和
- 可验证：第三方可重放验证
- 标准化：JSON Schema 定义，便于工具链处理

---

## 规模特定实现概要

### Minimal (~30 行)
```
核心: 内存中的 list，追加事件对象
没有持久化，进程退出即丢失
适用: 单次交互、不需要历史的场景
```

### Professional (~100 行)
```
核心: JSONL 文件，每次事件发生时 append 一行
实现要点:
  - 文件打开模式: a (append, 自动创建)
  - 每次写入后 flush (防崩溃丢失单行)
  - Session 创建时分配 UUID 作为文件名
  - 提供 load(session_id) 工厂方法从文件恢复
  - Session 过期后归档文件到 sessions/ 目录
```

### Enterprise (~300 行)
```
核心: 双写 - JSONL 文件 + PostgreSQL
实现要点:
  - JSONL 文件保持人类可读和快速重放
  - PostgreSQL 提供查询、聚合、审计检索
  - 异步写入：先写 JSONL (同步)，后写 DB (异步)
  - 一致性校验：定期比对 JSONL 和 DB 记录数
  - 压缩优化：满 1000 个 turn 后压缩历史 JSONL (gzip)
  - 事件去重：基于 uuid 幂等写入
```

---

⚠ **AI 构建提示**：

```
根据用户选择的规模实现 Session：

Minimal 级别：
  1. 创建 EventLog 类 (list-based)
  2. 提供 append(event_type, data) 方法
  3. 提供 replay() 方法遍历恢复状态
  4. 无需文件 I/O

Professional 级别：
  1. 创建 JSONLSession 类
  2. 构造函数中分配 UUID (uuid4)
  3. 每次事件触发时调用 _write_event() → 追加一行 JSON
  4. 实现类方法 load(session_id) 从文件恢复
  5. 实现 close() 方法（flush + 关闭文件句柄）
  6. 实现在 __del__ 或 context manager 中自动 close

Enterprise 级别：
  1. 扩展 Professional 实现，添加数据库写入
  2. 实现异步写入队列 (asyncio.Queue)
  3. 实现一致性校验作业（定时器）
  4. 添加压缩/归档策略
  5. 添加事件去重逻辑 (uuid set)

所有级别必须：
  □ 支持 replay() 方法重建状态
  □ 包含 timestamp 字段在每个事件中
  □ turn_start 和 turn_end 必须成对出现
  □ 提供当前状态查询 (is_idle, is_running, etc.)
```

---

# 耐久执行与检查点恢复 (v4)

> 配合 Phase 4 的 Loop Engineering 升级，引入耐久执行（Durable Execution）模式，使 Agent 循环具备"系统重启后继续"的能力。

## 设计原理

耐久执行的核心思想：每一步的状态写入持久化存储，工作流引擎能重新唤起并从中断的节点继续循环，而不是重新运行整个任务。

与现有 WAL 日志的关系：
- **WAL** 负责记录"发生了什么"（事件日志，用于审计和回放）
- **检查点（Checkpoint）** 负责记录"当前状态是什么"（完整快照，用于恢复）
- 两者互补：WAL 保证不丢事件，Checkpoint 保证快速恢复

## 检查点保存时机

| 触发条件 | 频率 | 说明 |
|---------|------|------|
| 每 N 轮循环 | 默认每 5 轮 | 常规检查点，防止状态丢失过多 |
| 计划变更 | 每次双层循环重规划时 | 外循环调整计划后立即存档 |
| 安全阻断 | SafetyGuardLoop 发出 BLOCK 时 | 阻断前保存现场，便于审计 |
| 人工断点前 | 可观测断点触发等待时 | 挂起前保存，恢复时从断点继续 |
| 会话结束 | 正常退出时 | 最终状态存档 |

## 检查点数据结构

```python
@dataclass
class CheckpointData:
    """持久化的检查点状态"""
    checkpoint_id: str
    session_id: str
    seq_id: int                        # 对应 WAL 中的序列号
    turn_count: int
    agent_state: str                   # IDLE / RUNNING / PAUSED / EXPIRED / ERROR
    messages_summary: str              # 压缩后的消息摘要（非完整消息列表）
    execution_plan: Optional[dict]     # 双层循环的执行计划状态
    pending_tasks: List[str]           # 未完成的任务列表
    active_files: List[str]            # 当前工作文件列表
    total_cost: float                  # 累计 Token 费用
    created_at: str                    # ISO 8601 时间戳
```

## 崩溃恢复流程

```
1. 加载最近检查点 → 获取 checkpoint_id 和 seq_id
2. 重放 WAL 中 seq_id 之后的事件 → 重建精确状态
3. 检查 execution_plan 中未完成的步骤 → 从中断步继续
4. 恢复 active_files 上下文 → 重新注入 system prompt
5. 继续 Agent 主循环
```

**关键约束**：
- 恢复代码必须是**确定性的**——给定相同的检查点和 WAL，必须产生相同的恢复结果
- 工具调用在恢复时需要**幂等性保证**——如果工具调用已完成但 WAL 未记录，恢复时可能重复执行，工具必须能处理
- 不可在恢复时调用 `random`、`datetime.now()` 等非确定性函数

## 与 Temporal.io 模式的关系

Temporal.io 是工业界耐久执行的事实标准。本项目采用**轻量级实现**，不引入 Temporal 依赖，但遵循其核心设计原则：

| Temporal 概念 | 本项目对应 |
|--------------|----------|
| Workflow | Agent 主循环（`AgentCore.run()`） |
| Activity | 工具调用（每次 `execute_tool()`） |
| Event History | Session WAL (`wal_{session_id}.jsonl`) |
| Workflow State | CheckpointData |
| Replay | `replay_session()` 从 WAL 重建 |

**规模适配**：
- **Minimal**：不使用耐久执行。崩溃后对话丢失。
- **Professional**：基础检查点（每 5 轮文件存档，JSON 格式）。
- **Enterprise**：完整检查点 + WAL 双重持久化，支持崩溃恢复和跨进程迁移。

## AI 构建提示

```
根据用户选择的规模实现耐久执行：

Professional 级别：
  1. 在 AgentCore 中每 5 轮调用 _save_checkpoint()
  2. 检查点保存为 JSON 文件：.checkpoints/{session_id}.json
  3. 恢复时加载检查点，从 turn_count 继续

Enterprise 级别：
  1. 实现 CheckpointManager 类，管理检查点生命周期
  2. 检查点保存到 Redis/数据库（非文件系统）
  3. 实现 LoopRecovery 类，编排恢复流程
  4. 支持跨进程迁移（从检查点 + WAL 在新进程中恢复）
  5. 检查点压缩：保留最近 3 个检查点，旧检查点归档

关键约束：
  □ 恢复代码不使用 random / datetime.now() 等非确定性函数
  □ 工具调用在恢复时检查幂等性（通过 tool_call_id 去重）
  □ 检查点保存必须是原子操作（先写临时文件，再 rename）
  □ 检查点包含 seq_id，与 WAL 对齐
```

---

# 第二部分：跨会话层（Cross-Session Layer）

> 进程内层保证"崩溃可恢复"，但**不解决"新会话从零恢复任务意图"**。
> checkpoint 里只有 `pending_tasks` / `active_files`——它告诉新会话"状态是什么"，
> 却没告诉新会话"任务是什么、为什么做、做到哪了、下一步该做什么"。
> 跨会话层用**结构化 handoff 文件**填补这个缺口。

## 何时读本节

- 任务需要**跨多个会话 / 跨天 / 跨人接手**（而非单次进程内运行）。
- 你发现新会话启动后，Agent 在"重新理解任务意图"上反复浪费 token。
- 你想让"压缩即摘要"之外的、**完整的上下文重置**成为默认机制。
- 你需要设计 Initializer / Coding 双角色，或制定项目的 handoff 文件规范。
- 与 `references/05-phase-context.md`（上下文压缩）和 `references/06-phase-permissions.md`（Budget 降级链）联动阅读。

---

## 现状问题：进程内恢复 ≠ 跨会话恢复

原进程内层存在三处硬缺口，导致"换一个全新会话"时无法从零接手：

| 缺口 | 进程内层做了什么 | 跨会话层缺什么 |
|---|---|---|
| 任务意图 | 只有 `pending_tasks`（字符串列表） | 没有 **feature list 结构**——feature 的粒度、判据、通过状态无从得知 |
| 进度语义 | 只有 `active_files`（当前文件） | 没有 **handoff 进度文件**——"做了什么 / 下一步 / 有什么意外"无规范 |
| 收尾协议 | 超时即 `expired`，状态丢弃 | 没有"**超时前产出阶段性总结**"的收尾，新会话接手时无上下文 |
| LLM 漂移 | "代码必须确定性"约束了工具侧 | 没约束 **LLM 侧漂移**（模型版本 / 温度 / seed），"同样检查点必得同样结果"实际不可达 |
| 归档 | JSONL 只追加，无限增长 | 没有 **滚动归档策略**，append-only 与存储/审计的取舍未说明 |

> 关键结论：在跨天尺度上，"压缩即摘要"不够——必须靠**结构化 handoff 文件做完整上下文重置**。
> 即便是最强模型，跨多个上下文窗口循环也做不出生产级应用，除非 harness 提供结构。

---

## 三件持久化产物 schema

跨会话层强制要求仓库根目录（或约定目录，如 `agent/` 或 `.agent/`）落地三件产物。
**全部用 JSON 或纯文本，不用 Markdown 承载机器读取的契约**——见下方 feature_list 的取舍说明。

### 1. `feature_list.json`

每个 feature 是"一次会话能做完"的最小工作单元；初始**全部标记 `passes: false`**。

```json
{
  "project": "agent-harness-engineer-skill",
  "schema_version": 1,
  "initialized_at": "2026-09-19T08:00:00Z",
  "features": [
    {
      "id": "F1",
      "title": "实现 WAL 事件追加写入",
      "granularity_criterion": "一个 feature 必须小到单次会话可完成：单次 PR、单测全绿、可独立 review",
      "acceptance": ["append 一行合法 JSONL", "turn_start/turn_end 成对", "flush 后不丢行"],
      "passes": false,
      "assigned_session": null,
      "done_at": null
    },
    {
      "id": "F2",
      "title": "实现 checkpoint 每 5 轮存档",
      "granularity_criterion": "同上；不依赖 F1 之外的未合并改动",
      "acceptance": ["生成 .checkpoints/{sid}.json", "原子写（临时文件 + rename）"],
      "passes": false,
      "assigned_session": null,
      "done_at": null
    }
  ]
}
```

**为什么用 JSON 而非 Markdown**：模型更少乱改。Markdown 表格一旦被 LLM"顺手润色"就会破坏结构，
而 JSON 有 schema 边界，编辑时更容易触发"这是契约、别瞎改"的约束意识；
且可被程序严格校验（`passes` 只能是布尔、feature 粒度有 `granularity_criterion` 判据）。

### 2. progress 文件（建议 `PROGRESS.md` 或 `agent/progress.txt`）

三字段纯文本，每次会话结束**必须**更新：

```
## 做了什么 (What I did)
- 完成 F1：WAL 追加写入 + flush 保证
- 修复 tool_result 缺 success 字段的边界 case

## 下一步 (Next step)
- 认领 F2：checkpoint 每 5 轮存档（最高优先级未完成 feature）

## 有什么意外 (Surprises)
- 发现 05 的压缩触发会污染 WAL 的 reason 枚举，已在 issue #42 记录，未改 schema
```

> 这三字段是 handoff 的"最小信息核"：新会话读它 + `git log` 即可获得足够上下文，
> 无需重放整个 WAL。

### 3. `init.sh` / bootstrap 契约

一次性脚本，负责把仓库带入"可接手"状态：装依赖、跑通基线测试、产出初始 `feature_list.json` 与首个 git commit。
它是对下方 **Bootstrap Contract 四问**的程序化兑现。

```python
class BootstrapContract:
    """Initializer Agent 一次性产出的引导契约。非可运行实现，仅接口骨架。"""
    def ensure_dependencies(self) -> None:
        raise NotImplementedError("AI: 实现依赖安装与版本锁定（如 poetry install / npm ci），失败则退出非零")

    def run_baseline_tests(self) -> bool:
        raise NotImplementedError("AI: 跑基线测试套件，返回是否全绿；不为零绿则初始化未完成")

    def emit_feature_list(self) -> None:
        raise NotImplementedError("AI: 生成 feature_list.json，每个 feature 初始 passes=false，粒度满足单次会话可完成")

    def initial_commit(self) -> None:
        raise NotImplementedError("AI: 提交 bootstrap 结果（init.sh + feature_list.json + 空 progress），作为可回滚基线")
```

---

## 双角色模型：Initializer Agent + Coding Agent

> 技术依据：Anthropic 的**长时运行 harness** 即采用此双角色结构——一个一次性初始化者，
> 加一个被反复唤醒的执行者。

```
┌──────────────────────────┐         ┌──────────────────────────┐
│   Initializer Agent       │         │   Coding Agent (反复唤醒) │
│   (跑一次)                │         │   (每个会话一次一个 feature)│
├──────────────────────────┤         ├──────────────────────────┤
│ 1. 装依赖                 │  产出   │ 每会话只读:              │
│ 2. 跑基线测试             │ ──────→ │   - PROGRESS.md          │
│ 3. 写 feature_list.json   │ init.sh │   - git log              │
│ 4. 初始 git commit        │         │ 然后:                    │
└──────────────────────────┘         │  - 认领一个 feature      │
                                      │  - 写代码 + 跑测试        │
                                      │  - 更新 progress          │
                                      │  - 提交（一个 feature 一提交）│
                                      └──────────────────────────┘
```

| 角色 | 触发次数 | 职责边界 | 产物 |
|---|---|---|---|
| Initializer Agent | 每个仓库**一次** | 建立"可接手"基线；不做业务功能 | `init.sh` + `feature_list.json` + 首个 commit |
| Coding Agent | **反复**唤醒 | 一次只做一个 feature，跑测试，更新 progress，提交 | 增量 commit + 更新的 `PROGRESS.md` |

> 铁律：**Coding Agent 一次会话只做一个 feature**。做完、测试绿、更新 progress、提交，然后退出。
> 绝不在同一会话内顺手做下一个 feature——那会让"单次会话可完成"的粒度约定失效。

---

## 五步会话初始化仪式（harness 强制）

> 这套"热身"实际**省 token**：先花几步对齐上下文，远比让 Agent 在错误假设上盲写便宜。

下列步骤**必须由 harness 强制**，不依赖 Agent 自觉——在系统提示或启动钩子里写死：
**"必须完成步骤 1–4 才能写代码"**。每步要求输出**一行可审计的状态**。

```
[检查清单] 会话初始化仪式（harness 强制，步骤 1-4 未完成禁止写代码）

☐ Step 1  确认工作目录
     → 输出: `DIR: <abs_path>  (git root: <yes/no>)`
☐ Step 2  读 git log 与 PROGRESS.md
     → 输出: `CTX: last_commit=<sha>  progress_lines=<n>  open_features=<ids>`
☐ Step 3  选最高优先级未完成 feature
     → 输出: `PICK: feature=<id>  reason=<为何最高优先级>`
☐ Step 4  跑基线测试（确认起跑线绿）
     → 输出: `BASELINE: pass=<n> fail=<n>  (若 fail>0 则先修基线，不写新代码)`
☐ Step 5  才开始写代码
     → 输出: `START: feature=<id>  (此后才允许编辑源码)`
```

`AI 构建提示`：
```
实现 harness 启动钩子，强制上述 5 步：
  □ Step 1-4 任何一步失败 / 未产出对应状态行，则拦截后续 edit/write 工具调用
  □ Step 4 基线不绿时，将当前会话重定向为"修基线"会话，禁止新增 feature
  □ 每步状态行写入 WAL 作为 turn_start 的附属元数据，便于审计
```

---

## Bootstrap Contract 四问（初始化完成的验收条件）

Initializer Agent 完成后，一个**全新会话只看仓库内容**就能回答以下四问，才算初始化真正完成：

| # | 问题 | 验证方式（只读仓库） |
|---|---|---|
| 1 | **能启动？** | 仓库存在 `init.sh` 且可被执行，依赖可装、环境可起 |
| 2 | **能测试？** | 存在可一键运行的测试命令，`feature_list.json` 的 `acceptance` 可被程序校验 |
| 3 | **能看到进度？** | 存在 `PROGRESS.md` + `feature_list.json`，`passes` 字段反映真实状态 |
| 4 | **能接手下一步？** | 存在至少一个 `passes: false` 的 feature，且其 `granularity_criterion` 明确到单次会话可完成 |

> 任一问答不上来，Initializer 的初始化即视为**未完成**，Coding Agent 不应开工。

---

## test ratchet（测试棘轮）

> 堵住 Agent 最常见的作弊捷径：**删掉或编辑失败的测试让它通过**。

在系统提示 / harness 约束中写死：

```
TEST RATCHET（不可违反）：
- 删除已有测试文件或测试函数 → 不可接受
- 编辑已有断言使其放宽以"变绿" → 不可接受
- 用 @skip / xfail 掩盖失败 → 不可接受（除非该 feature 明确标记为 known-fail 并由 human 确认）
- 唯一允许的路径：让生产代码通过测试，或新增测试覆盖新行为
违反上述任一条，harness 应在提交前拦截（pre-commit 钩子比对测试文件 diff）
```

`AI 构建提示`：
```
实现 test ratchet 守卫（接口骨架）：
  class TestRatchet:
      def guard(self, diff) -> bool:
          raise NotImplementedError("AI: 解析 git diff，发现测试文件被删除/被放宽断言/被 skip 时返回 False 并报警")
      def require_new_or_passing(self, test_report) -> bool:
          raise NotImplementedError("AI: 校验本次改动未减少测试总数且目标 feature 的 acceptance 全绿")
```

---

## LLM 侧可复现性约束

原进程内层要求"代码必须确定性"，但**只约束了工具侧**，没约束 LLM 侧漂移。
"给定相同检查点必得相同结果"在 LLM 参与下实际不可达，除非把采样上下文也钉死。

**要求**：检查点元数据必须携带以下 LLM 采样信息（扩展原 `CheckpointData`）：

```python
class CheckpointMetadata:
    """检查点元数据——跨会话可复现性的关键约束（扩展原 CheckpointData）"""
    session_id: str
    seq_id: int
    model_id: str            # 例如 "claude-opus-4"
    model_version: str       # 模型服务/权重版本，用于对齐
    temperature: float       # LLM 采样温度
    seed: int                # 采样随机种子
    created_at: str

    def verify_reproducible(self, baseline: "CheckpointMetadata") -> bool:
        raise NotImplementedError(
            "AI: 比较 model_id/model_version/temperature/seed 是否一致；"
            "不一致时警告：恢复结果可能漂移，跨会话不可假定确定性"
        )
```

| 字段 | 作用 | 漂移后果 |
|---|---|---|
| `model_id` | 钉死模型族 | 换模型 → 行为分布改变 |
| `model_version` | 钉死权重/服务版本 | 同 id 不同版本 → 隐性漂移 |
| `temperature` | 钉死采样随机性 | >0 时同输入不同输出 |
| `seed` | 钉死随机种子 | 无 seed → 不可复现 |

> 即便全部钉死，`temperature>0` 仍不保证逐 token 一致；此约束的目标是**让跨会话恢复"可对齐、可归因"**，而非逐字节确定性。

---

## 上下文重置优于压缩的触发条件

> 与 `references/05-phase-context.md`（上下文压缩）联动：压缩是"摘要"，重置是"换脑子"。

当满足以下任一条件时，**优先做完整上下文重置（读 handoff 文件 + git log），而非依赖 05 的压缩摘要**：

| 触发条件 | 说明 | 动作 |
|---|---|---|
| 跨会话 / 跨天唤醒 | 新会话从零开始，WAL 上下文已不可见 | 走五步初始化仪式，读 `PROGRESS.md` + `git log` |
| 压缩摘要已超 N 轮 | 05 的摘要本身开始失真（见 05 的阈值） | 丢弃摘要，从 `feature_list.json` + progress 重建 |
| 任务意图变更 | 用户改了目标，旧摘要误导 | 重置，重新认领 feature |
| 模型/配置漂移 | `CheckpointMetadata` 校验失败 | 重置并标注 drift，不假装连续 |

```
判断流程:
  新会话启动
    ├─ 有 PROGRESS.md + feature_list.json? ── 是 ──→ 走五步仪式（重置）
    └─ 否 ──→ 走 05 压缩恢复（仅当同进程内有可接续 WAL）
```

---

## 超时前先产出阶段性总结再终止（收尾协议）

> 与 `references/06-phase-permissions.md` 的 Budget 降级链末级 **TERMINATE_HANDOFF** 打通。

进程内层超时即 `expired` 并丢弃状态——这对跨会话是灾难：新会话接手时毫无上下文。
**收尾协议**：在 `TERMINATE_HANDOFF` 触发（或任何 `reason=timeout`）之前，**必须先更新 `PROGRESS.md` 的"做了什么 / 下一步 / 有什么意外"三字段，再终止**。

```
TERMINATE_HANDOFF 收尾序列（harness 强制）:
  1. 写 PROGRESS.md:
       - 做了什么: 已完成的 feature / 已改文件
       - 下一步:   明确下一个最高优先级未完成 feature
       - 有什么意外: 阻塞、已知坑、未决决策
  2. 更新 feature_list.json: 已完成 feature 标 passes=true
  3. 提交（或标注未提交原因）
  4. 才允许 reason=timeout 终止
```

> 这样即使会话被 Budget 链强制终止，下一个被唤醒的 Coding Agent 也能从 progress 无缝接手，
> 而不是从零"猜"任务意图。

---

## WAL 滚动归档策略

原进程内层只要求 append-only、无限追加，未定义归档。跨会话层给出明确策略，并正视与"审计不可篡改"的冲突。

| 策略项 | 规则 |
|---|---|
| **归档触发** | 每次生成检查点（`CheckpointData`）成功后，将 `seq_id` 之前的 WAL 段归档 |
| **归档单位** | 按 `checkpoint_id` 切分，归档为 `wal_{session_id}_{checkpoint_id}.jsonl.archive` |
| **保留期** | Professional 保留最近 7 天 / 最近 50 个归档；Enterprise 按合规保留期（如 180 天） |
| **在线 WAL** | 仅保留当前活跃段（未归档部分），控制单文件大小与重放成本 |
| **校验** | 归档时写入 SHA-256 清单，恢复时校验，防止归档损坏 |

**与 append-only 审计要求的取舍**：

```
冲突本质:
  - 审计要求: WAL 永不修改、永不删除（append-only, immutable）
  - 存储/性能要求: 单文件无限增长 → 重放慢、磁盘爆

本项目取舍:
  ✅ 归档 ≠ 删除: 归档是把"已 checkpoint 的旧段"移到 .archive/，原内容不变、只读
  ✅ 在线活跃段仍严格 append-only; 只有"已安全 checkpoint 的段"才允许移出活跃文件
  ⚠ 若合规硬性要求"原文件物理不可移动", 则改为: 活跃文件保留, 另写 .archive/ 副本,
     原文件标记 frozen 但保留在线上 (牺牲磁盘换合规)
  ❌ 绝不允许就地 truncate / 改写历史事件
```

`AI 构建提示`：
```
实现 WAL 归档（接口骨架）:
  class WALArchiver:
      def archive_upto(self, checkpoint_id: str, seq_id: int) -> None:
          raise NotImplementedError("AI: 将 seq_id 之前的 WAL 段复制到 .archive/ 并写 SHA-256 清单；不得修改原段")
      def prune_online(self, keep_recent: int) -> None:
          raise NotImplementedError("AI: 仅在合规允许时，将已归档段移出活跃文件；保留最近 keep_recent 段在线")
```

---

## 规模适配（跨会话层）

| 规模 | 跨会话层要求 | 说明 |
|---|---|---|
| **Minimal** | 不涉及 | 单次交互，无跨会话需求；进程内层已够 |
| **Professional** | 单会话内 `PROGRESS.md` | 不强制 Initializer 角色；同一开发者多次唤醒时手写 progress 即可，feature_list 可简化 |
| **Enterprise** | 完整 Initializer / Coding 双角色 + `feature_list.json` + 跨天重置 | 强制五步仪式、Bootstrap Contract 四问、test ratchet、WAL 归档、LLM 元数据；跨天唤醒必走上下文重置 |

---

## Ralph 循环：同形状的开源等价物

本跨会话层的双角色 + handoff 设计，与开源的 **Ralph 循环** 同形状：

- **PRD** ≈ 本文件的 `feature_list.json`（结构化的、可程序校验的任务清单）
- **append-only progress** ≈ 本文件的 `PROGRESS.md` 三字段（每次只追加"做了什么/下一步/意外"）
- **AGENTS.md 每轮更新** ≈ 五步初始化仪式中"读 progress + git log"的等价物（每轮从仓库自描述重建上下文）

> Ralph 的价值在于用**极简的仓库自描述**替代"把上下文塞进对话窗口"，
> 这与本文件"上下文重置优于压缩"的结论一致：结构在仓库，不在上下文窗口。

---

## 技术依据

- **Anthropic 长时运行 harness**（当前参考结构）：即本文件的双角色模型——Initializer 跑一次建立基线，Coding Agent 反复唤醒推进 feature。
- **关键结论**：在跨天尺度上，"压缩即摘要"不够——必须靠**结构化 handoff 文件做完整上下文重置**。即便是最强模型，跨多个上下文窗口循环也做不出生产级应用，除非 harness 提供结构。
- **Anthropic Project Vend**（Claude 经营一个月的自动售货业务）：列出了跨周一致性失效的完整目录——意图漂移、进度丢失、重复劳动、未决决策被遗忘。这证明跨会话交接不是理论问题，而是真实失败模式；本文件的 feature_list + progress + 五步仪式正是针对该目录的对策。
