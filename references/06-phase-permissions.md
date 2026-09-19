# Phase 6: 权限安全

## 目标

构建多层纵深防御的权限与安全体系，确保Agent在任何规模下都运行在可控边界内，杜绝逃逸、提权、配置篡改。

---

## 设计原理

单一防御层对AI Agent而言形同虚设——LLM的创造性与不确定性意味着任何单点校验都可能被绕过。正确的安全架构应该遵循三个核心原则：

### 原则一：纵深防御（Defense in Depth）

每一层拦截一部分风险，多层叠加使绕过概率指数下降。即使某一层被攻破，后续层仍然生效。

### 原则二：安全优先不可变量

`deny > settings rules > hook allow` 是铁律，任何代码路径都不能打破这个优先级链。硬编码拒绝条目不可通过配置、Hook或任何运行时机制覆盖。

### 原则三：最小权限 + 凭证外置

Agent不应该拥有它不需要的权限。凭证（API Key、Token、密码）永远不进入沙箱——通过凭证外置架构，Agent请求操作时由宿主环境注入，Agent自身无法读取原始凭证。

---

## 纵深防御架构

六层防御从外到内逐层收紧：

```
┌─────────────────────────────────────────────────────┐
│  Layer 6: Hardcoded Denies                          │
│  不可变拒绝清单（settings.json/.claude/skills 写保护）│
├─────────────────────────────────────────────────────┤
│  Layer 5: Audit Logging                             │
│  Session = Audit Log，全量记录不可删除               │
├─────────────────────────────────────────────────────┤
│  Layer 4: Sandbox                                   │
│  文件系统隔离 + 网络隔离 + 进程隔离                   │
├─────────────────────────────────────────────────────┤
│  Layer 3: Hook System                               │
│  26个事件 × 4种类型：PreToolUse/PostToolUse/         │
│  UserPromptSubmit/Stop/SessionStart                 │
├─────────────────────────────────────────────────────┤
│  Layer 2: AI Classifier                             │
│  YOLO自动批准：AI判断低风险操作直接放行               │
├─────────────────────────────────────────────────────┤
│  Layer 1: Permission Model                          │
│  5种模式 × 7级规则层级                              │
└─────────────────────────────────────────────────────┘
```

### Layer 1：权限模型（Permission Model）

**5种权限模式：**

| 模式 | 含义 | 适用场景 |
|------|------|----------|
| `default` | 继承`settings.json`全局设置 | 普通操作 |
| `accept_edits` | 自动接受文件编辑，其他仍需确认 | 可信仓库开发 |
| `bypass_permissions` | 跳过所有权限检查（仅限IDE集成场景） | IDE内可信环境 |
| `plan` | 只读模式，仅允许分析类操作 | 调研/代码审查 |
| `accept_all` | 自动批准所有（最高危，不推荐） | 无人值守CI |

**7级规则层级（优先级从高到低）：**

1. **Hardcoded Deny** — 编译期/启动期注入，运行时不可修改。覆盖一切。
2. **Rule Level `deny` in settings** — 用户配置的显式拒绝规则，高于所有allow。
3. **Rule Level `ask` in settings** — 需要弹窗确认的规则，用户交互后才决策。
4. **Hook allow** — Hook系统可以建议allow，但不能覆盖deny。
5. **Hook deny** — Hook建议拒绝，但低于settings deny。
6. **YOLO auto-approve** — AI分类器对低风险操作自动放行。
7. **Default fallback** — 无匹配规则时取`settings.json`中`permissions.defaultMode`。

### Layer 2：AI分类器（YOLO Auto-Approval）

在Layer 1判定为"需要确认"时，AI分类器介入做二次判断。设计要点：

- **输入**：工具名 + 参数摘要 + 当前会话上下文
- **分类维度**：
  - 操作类型（读/写/执行/网络/进程）
  - 目标路径是否在worktree内
  - 命令中是否含危险模式（pipe、redirect、delete）
  - 历史类似操作是否被拒绝过
- **输出**：`safe`（自动放行）、`unsafe`（回退到ask）、`unknown`（强制确认）
- **约束**：YOLO不得否决deny规则。YOLO输出`safe`不等于跳过Layer 1的deny检查，只在Layer 1返回`allow_or_ask`时才生效。

### Layer 3：Hook系统（Hook System）

Hook是Agent生命周期的可编程拦截点。系统设计为26个事件 × 4种类型：

**4种事件类型：**

| 类型 | 触发时机 | 典型用途 |
|------|----------|----------|
| `PreToolUse` | 工具调用前 | 参数校验、路径改写、风控拦截 |
| `PostToolUse` | 工具调用后 | 输出脱敏、结果审计、副作用弥补 |
| `UserPromptSubmit` | 用户提交提示词时 | 注入上下文、敏感词过滤 |
| `Stop` | Agent停止/会话结束时 | 资源回收、报告生成、指标收集 |
| `SessionStart` | 会话初始化时 | 环境检查、权限预加载、凭证注入 |

**26个事件覆盖点：**

- 工具类事件（8个）：Pre/Post × BashTool, FileReadTool, FileWriteTool, FileEditTool
- 交互类事件（4个）：UserPromptSubmit, Notification, SubagentStart, SubagentStop
- 生命周期事件（4个）：SessionStart, Stop, Resume, Idle
- 沙箱事件（4个）：PreSandboxExec, PostSandboxExec, SandboxError, CredentialRequest
- 审计事件（3个）：PermissionDenied, PermissionGranted, YOLOOverride
- 扩展事件（3个）：自定义事件槽位，供插件/MCP Hook注入

Hook之间独立运行，一个Hook抛出异常不影响其他Hook执行。Hook返回的修改数据通过管道传递到下一Hook和原始调用链。

### Layer 4：沙箱（Sandbox）

三向隔离构成沙箱：

- **文件系统隔离**：Agent只能访问白名单目录集合。所有路径在操作前经过`validate_path`，解析符号链接和`..`后再判定。worktree外的读取需要显式授权。
- **网络隔离**：默认阻断所有出站网络。白名单域名/端口在配置中显式声明。DNS解析通过受控代理。
- **进程隔离**：Agent启动的子进程在受限环境中运行。禁止`fork`、`exec`链。管道和重定向在解析阶段被限制。

沙箱与Hook系统的交互：`PreSandboxExec` Hook可以在命令进入沙箱前做最后一道拦截。`SandboxError` Hook捕获沙箱内异常，防止错误信息泄露宿主机路径。

### Layer 5：审计日志（Audit Logging）

设计核心理念：**Session = Audit Log**。每个会话本身就是不可变审计记录。

- 全量记录：每次权限检查结果、每个Hook调用、每条沙箱决策、每个工具调用的输入输出摘要。
- 不可变写入：日志流一旦写入不可修改、不可截断。Agent自身无写权限。
- 结构化格式：每条日志包含`timestamp`、`session_id`、`layer`、`decision`、`context`字段。
- 保留策略：按组织合规要求设置（默认90天），支持导出到SIEM。

### Layer 6：硬编码拒绝（Hardcoded Denies）

这是终极安全线。以下条目在代码中硬编码，运行时不可通过任何机制关闭：

- `settings.json` 文件本身：Agent不可读写
- `.claude/` 目录下所有配置文件：Agent不可修改
- 沙箱配置路径：硬编码为只读，禁止Agent通过修改配置关闭沙箱
- 审计日志目录：Agent不可写入或删除日志
- MCP工具清单中的`always_ask`默认值：第三方MCP工具默认需要确认

---

## 抽象接口层

以下为AI构建时必须实现的抽象接口签名——无具体实现，AI需要根据项目语言和框架自行完成。

### PermissionRule（抽象数据模型）

- 属性：`pattern`（匹配模式，支持glob）、`action`（deny|allow|ask）、`level`（对应7级层级中的编号）、`scope`（作用域：tool|path|network|process）
- 方法：`matches(tool_name, params) -> bool` — 判定当前工具调用是否命中此规则
- 方法：`priority() -> int` — 返回层级优先级数值，排序用

### PermissionManager（抽象管理器）

- `check_permission(tool_name, tool_input, session_context) -> PermissionDecision`  
  遍历规则层级0-6，返回最早命中的决策。决策对象包含`action`、`matched_rule`、`reason`。
- `add_rule(pattern, action, level, scope) -> None`  
  仅允许在settings规则层级（level 1-3）添加。level 0和6被硬编码保护。
- `remove_rule(pattern) -> None`  
  仅允许移除level 1-3的规则。level 6不可移除。
- `get_effective_rules() -> List[PermissionRule]`  
  返回当前生效的完整规则集，含硬编码规则和用户规则。
- 不可变量检查：每次`check_permission`调用前断言deny > hook allow。

### HookSystem（抽象Hook管理器）

- `register_hook(event_type, callback, priority=50) -> HookHandle`  
  注册Hook到指定事件类型。priority越小越先执行。返回句柄用于后续注销。
- `execute_pre(tool_name, tool_input, session_context) -> ModifiedInput`  
  按优先级执行所有PreToolUse Hook。返回经Hook链修改后的输入。
- `execute_post(tool_name, tool_input, tool_output, session_context) -> ModifiedOutput`  
  按优先级执行所有PostToolUse Hook。返回经Hook链修改后的输出。
- `unregister(hook_handle) -> None` — 注销Hook。
- `list_hooks(event_type) -> List[HookDescriptor]` — 列出已注册Hook。
- Hook回调签名规范：
  - PreToolUse: `(tool_name, tool_input, context) -> tool_input'`
  - PostToolUse: `(tool_name, tool_input, tool_output, context) -> tool_output'`
  - UserPromptSubmit: `(prompt_text, context) -> prompt_text'`
  - Stop: `(reason, context) -> None`

### SandboxManager（抽象沙箱管理器）

- `validate_path(path, operation_type) -> PathDecision`  
  解析路径（消除`.`、`..`、符号链接），判定是否在白名单内。PathDecision含`allowed`、`resolved_path`、`matched_rule`。
- `validate_command(command_string) -> CommandDecision`  
  解析命令字符串，检测管道/重定向/危险模式。CommandDecision含`allowed`、`sanitized_command`、`risk_score`。
- `wrap_execution(command, env, workdir) -> ProcessHandle`  
  在隔离环境中执行。返回ProcessHandle含`stdout_stream`、`stderr_stream`、`wait()`、`kill()`方法。
- `credentials_request(credential_id) -> Credential`  
  凭证外置：Agent请求`credential_id`，沙箱向宿主环境请求注入，Agent自身不接触原始值。返回临时注入的句柄。
- 隔离配置：`network_policy`（deny_all | allowlist）、`fs_policy`（whitelist_paths）、`resource_limits`（cpu/memory/timeout）。

---

## 沙箱技术对比

选择沙箱技术时需权衡启动速度、隔离强度、运维复杂度：

| 技术 | 启动时间 | 隔离强度 | 性能开销 | 适用场景 |
|------|----------|----------|----------|----------|
| **Docker** | 见 `references/12-sandbox-advanced.md` | 中等（共享内核） | 低 | Professional规模，单机/单租户 |
| **Firecracker** | 见 `references/12-sandbox-advanced.md` | 高（microVM） | 中等 | Enterprise规模，多租户强隔离 |
| **gVisor** | 见 `references/12-sandbox-advanced.md` | 中高（用户态内核） | 中等 | 需要Docker兼容但需更强隔离 |
| **WebAssembly** | 见 `references/12-sandbox-advanced.md` | 指令级隔离 | 极低 | 插件/小工具沙箱，性能敏感场景 |
| **bubblewrap** | 见 `references/12-sandbox-advanced.md` | 中等 | 低 | Linux原生，Claude Code采用方案 |

> 启动时间等性能数据以 `references/12-sandbox-advanced.md` 为**单一事实源**，本文不重复保留易失真的数字（如 Docker 启动时间，12 记为 ~200ms；bubblewrap 记为 ~5ms）。

**选型建议：**

- 个人/小团队开发 → bubblewrap（零基础设施依赖）或Docker
- 团队CI/CD → Docker + 限权容器（`--read-only`、`--cap-drop=ALL`）
- SaaS多租户 → Firecracker（microVM强隔离，单租户单VM）
- 浏览器/边缘环境 → WebAssembly（指令级沙箱，零冷启动）
- 本地IDE Agent → bubblewrap（Claude Code路线验证），Linux宿主机原生支持

**不可变约束**：无论选择哪种技术，沙箱配置文件路径必须硬编码为只读。Agent在任何情况下都不得修改沙箱启动参数或挂载点。

---

## 预算与成本控制（权限的第四个维度）

**何时读本节**：当你需要限制 Agent 在一个任务 / 会话内能花多少 token、多少美元、多少个 turn、多少墙钟时间，并希望在逼近或突破上限时**自动降级**而非无限重试时，读本节。预算不是"能不能做"（Layer 1 权限模型），而是"还能花多少"——它是权限体系之外的第四个约束维度，与 Layer 1–6 正交。

### 设计原理

单一权限模型回答"这个操作能否执行"，但不回答"这样执行下去会花多少"。一个任务可能 3 步完成，也可能 30 步还完不成——**度量单位是 cost per task（每任务成本），不是 cost per token**。没有 tracing 就看不到成本罪魁：通常是臃肿的工具结果（大段未裁剪的 stdout）、冗余的验证轮次（同一事实反复确认）、未缓存的前缀（每次重复发送系统提示）。

三条工程杠杆（路由实现见 `references/02-phase-llm.md` 的 ModelRouter）：

1. **模型分层路由**：路由 / 工具选择 / 分类 / 简单步骤走小模型，前沿模型只留给真正难的推理。RouteLLM 一类方案报告在保持约 95% 质量的同时降本约 85%。
2. **步数压缩**：ReWOO / plan-execute 把 10 次工具的任务从 11 次调用压到约 2 次，可预测工作流省 30–50%（代价是对意外返回适应性差）。
3. **Batch API**：输入输出 5 折，适合评测跑批与夜间任务，可与 prompt caching 叠加。

> **核心铁律**：预算必须**绑定动作**而不只是告警——只告警不动作的预算等于没有预算。

### 抽象接口

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Callable


class DegradeAction(Enum):
    """预算预警与四级降级链的全部取值。"""
    NO_OP = "no_op"                            # 未超限，无动作
    WARN = "warn"                              # 预警（on_warning 默认，不阻断）
    DOWNGRADE_MODEL = "downgrade_model"        # 降级链 L1：切到更便宜模型
    STRIP_TOOLS_CONTEXT = "strip_tools_context"  # 降级链 L2：削减工具与上下文
    PAUSE_FOR_HUMAN = "pause_for_human"        # 降级链 L3：暂停请求人工批准
    TERMINATE_HANDOFF = "terminate_handoff"    # 降级链 L4：终止并产出交接


@dataclass
class Budget:
    """单任务 / 会话的成本与资源上限。单位必须显式声明。"""
    max_tokens: int = 0                    # 单位：token（含 prompt + completion），0 视为 unlimited
    max_cost_usd: float = 0.0              # 单位：美元（USD），跨模型按各自单价折算
    max_turns: int = 0                     # 单位：Agent 决策轮次（一次工具往返记 1 turn）
    max_wall_clock_seconds: float = 0.0    # 单位：墙钟秒（真实流逝时间，含等待）
    # ⚠ AI构建提示: 四字段至少填一个；max_tokens 与 max_cost_usd 建议同时约束，
    # ⚠ AI构建提示: 避免单价突变导致 token 未超限但费用爆炸。


@dataclass
class BudgetPolicy:
    """超限后的行为契约。on_warning 在逼近阈值时触发，on_exceeded 在突破阈值时触发。"""
    warning_threshold: float = 0.8             # 用量达到该比例即触发 on_warning（0–1）
    on_warning: DegradeAction = DegradeAction.WARN
    on_exceeded: DegradeAction = DegradeAction.TERMINATE_HANDOFF
    # ⚠ AI构建提示: on_exceeded 默认必须为降级链末级（TERMINATE_HANDOFF），
    # ⚠ AI构建提示: 不可默认为 WARN，否则预算形同虚设。


class BudgetController(ABC):
    """预算控制核心。每个主循环检查点调用 check()，返回应执行的降级动作。"""

    @abstractmethod
    def attach_checkpoint(self, phase: str, hook: Callable) -> None:
        """将检查点挂到主循环指定阶段（如 pre_action / post_action）。06 定义契约，Phase 4 实现。"""
        raise NotImplementedError("AI: 在 Phase 4 主循环的 pre/post 处注册回调，回调内调用 check() 与 record_usage()")

    @abstractmethod
    def check(self, consumed: Budget, task_id: str) -> DegradeAction:
        """评估当前用量，返回应执行的降级动作（NO_OP / WARN / 四级降级之一）。"""
        raise NotImplementedError("AI: 取已消耗 token/cost/turns/seconds，与 Budget 四字段逐一比较；"
                                  "未超限返回 NO_OP，逼近阈值返回 on_warning，突破返回 on_exceeded")

    @abstractmethod
    def record_usage(self, delta_tokens: int, delta_cost_usd: float,
                     delta_turns: int, delta_seconds: float, model: str) -> None:
        """由 tracing 在每个检查点上报增量用量；这是 cost-per-task 可观测的基础。"""
        raise NotImplementedError("AI: 接 tracing，按 task_id 累加用量；模型路由切换后仍需持续上报，否则成本归因失真")
```

### 四级降级链

预算突破后**逐级**收紧而非一步终止——给任务自救机会，但每级都有真实动作：

```
WARN（预警，on_warning 默认）: 写审计日志 + 推送通知(Slack/PagerDuty)，不阻断

┌─ 降级链 L1  DOWNGRADE_MODEL ───── 经 ModelRouter 把后续步骤切到 cheap 模型
├─ 降级链 L2  STRIP_TOOLS_CONTEXT ── 削减非核心工具(仅留白名单) + 裁剪上下文(丢弃陈旧工具结果)
├─ 降级链 L3  PAUSE_FOR_HUMAN ────── 暂停并请求人工批准，不自动继续
└─ 降级链 L4  TERMINATE_HANDOFF ──── 终止任务，产出阶段性交接(见 references/13-long-running-session.md)
```

四级降级链直接针对成本罪魁：L1 砍模型单价，L2 砍臃肿工具结果与冗余验证，L3/L4 在仍失控时停下来而非放任无限重试。

### 挂到主循环的契约

06 只定义契约，主循环实现由 Phase 4 负责：

- **检查点**：`pre_action`（行动前，校验本步是否会突破预算）与 `post_action`（行动后，上报实际用量）。
- **返回值消费**：`BudgetController.check()` 返回的 `DegradeAction` 由主循环解释执行；`WARN` 不阻断，`TERMINATE_HANDOFF` 触发 handoff。
- **与护栏子循环协同**：预算检查是「安全护栏子循环」Pre-Action 阶段 `budget_limit` 规则的具体实现（见下文 v4 章节）。
- **错误分类**：预算终止属于不可自动恢复错误，**不进入 REPLAN 的可自动重试集合**；错误分类权威定义见 `references/08-core-concepts.md`。

### 三档差异表

| 维度 | Minimal | Professional | Enterprise |
|------|---------|--------------|------------|
| Budget 字段 | 仅 `max_turns` | `max_turns` + `max_cost_usd` | 四字段全约束 |
| 降级链 | 仅 WARN 告警 | L1–L2 | L1–L4 全链 |
| 模型路由 | 无（单模型） | `on_exceeded` → DOWNGRADE_MODEL | 动态 RouterLLM 式路由 |
| 步数压缩 | 无 | plan-execute 可选 | ReWOO / plan-execute 默认开启 |
| Batch API | 不启用 | 夜间跑批启用 | 评测 + 夜间全量启用 |
| tracing | 无（无法定位罪魁） | 基础用量日志 | 全量 tracing + 成本归因面板 |

### AI 构建提示

```
根据用户选择的规模实现预算控制：

Minimal：
  1. 仅实现 max_turns 计数，超限即终止并写日志
  2. 不引入 tracing、不做模型路由

Professional：
  1. 实现 Budget / BudgetPolicy 骨架与 BudgetController.check()
  2. on_warning=WARN, on_exceeded 触发 DOWNGRADE_MODEL
  3. 接 ModelRouter（见 02）做后续步骤降级
  4. post_action 上报用量到基础日志

Enterprise：
  1. 四字段同时约束，默认 on_exceeded=TERMINATE_HANDOFF
  2. 接全量 tracing，按 task_id 归因（识别臃肿工具结果/冗余验证/未缓存前缀）
  3. ReWOO/plan-execute 压缩步数，Batch API 跑批
  4. TERMINATE_HANDOFF 调用 references/13-long-running-session.md 的交接契约
  5. 预算超限一律绑定动作，禁止"只告警"

关键约束：
  □ 预算必须绑定动作，不得只告警（核心铁律）
  □ max_cost_usd 与 max_tokens 建议同时约束
  □ 模型切换后仍持续上报用量，否则 cost-per-task 失真
  □ 预算终止不进入 REPLAN 自动重试集合
```

---

## AI构建提示

构建本Phase时，AI不应直接复制代码，而应根据以下提示自行实现：

1. **先建接口契约**：以上述抽象接口层为契约，用`Protocol`（Python）或`interface`（TypeScript）定义类型骨架。确保所有实现类满足接口签名。
2. **规则引擎使用策略模式**：不要用if-else链实现`check_permission`。用优先级排序 + 责任链模式遍历7级规则。
3. **Hook系统用发布-订阅模型**：事件总线解耦Hook注册和执行。Hook之间不互相依赖。
4. **沙箱层用工厂模式**：根据配置选择底层沙箱技术（Docker/Firecracker/bubblewrap），上层接口统一。
5. **审计日志用异步写入**：日志写入不能阻塞Agent工具调用。使用异步队列 + 批量刷盘。
6. **测试优先**：优先编写Layer 1的权限规则测试、Layer 3的Hook执行顺序测试、Layer 4的路径校验测试。
7. **凭证外置实现**：SandboxManager内部不持有凭证。`credentials_request`通过IPC向宿主守护进程请求，返回一次性注入的环境变量。
8. **MCP工具默认always_ask**：任何通过MCP协议注册的第三方工具，在规则引擎中默认level=`ask`，除非用户显式在settings中将其设为`allow`或`yolo`。

---

## 规模适应性指南

### Minimal（最小可行）

适用于单人项目、本地原型开发：

- 仅实现Layer 1（Permission Model）简化版：`deny` + `allow`两种action，无Hook系统。
- 沙箱：命令黑名单（`rm -rf`、`sudo`、`mkfs`等），不做文件系统隔离。
- 无审计日志。
- 代码量：~200行。
- 安全假设：信任当前用户和本地环境。

### Professional（专业级）

适用于团队内部使用、CI/CD集成：

- Layer 1完整实现（5模式 × 7层级）。
- Layer 3：Hook系统，至少支持PreToolUse和PostToolUse。
- Layer 4：Docker沙箱 + `--read-only`文件系统 + `--cap-drop=ALL`。
- Layer 5：基础审计日志，JSON格式写入只读卷。
- Layer 6：硬编码拒绝`settings.json`修改。
- 沙箱：Docker，工作目录挂载为只读或白名单路径。
- 代码量：~800-1200行。

### Enterprise（企业级）

适用于多租户SaaS、金融/医疗合规场景：

- **全部6层完整实现**。
- Layer 1：自定义规则DSL，支持正则、glob、语义级匹配。
- Layer 2：AI分类器，使用独立模型做风险评分（非Agent所用的LLM），防模型对抗。
- Layer 3：26个事件全覆盖，Hook热加载/热卸载。
- Layer 4：Firecracker microVM，每租户独立VM，网络完全隔离。
- Layer 5：全量审计日志 + SIEM导出 + 异常告警。
- Layer 6：所有配置路径硬编码，启动时哈希校验防止篡改。
- 凭证外置：通过Vault/Secrets Manager，Agent零接触。
- 合规：SOC2预备审计轨迹，每操作可追溯到会话、用户、令牌、时间窗口。

---

## 检查清单

- [ ] PermissionModel实现5种模式（default/accept_edits/bypass_permissions/plan/accept_all）
- [ ] 7级规则优先级正确：hardcoded deny > settings deny > ask > hook allow > hook deny > yolo > default
- [ ] `check_permission`遍历时不短路——即使deny命中，仍记录完整决策链用于审计
- [ ] YOLO分类器不会否决deny规则（Layer 2不能覆盖Layer 1的deny）
- [ ] Hook系统：PreToolUse、PostToolUse、UserPromptSubmit、Stop、SessionStart事件已注册
- [ ] Hook异常不影响其他Hook和原始调用链（异常隔离）
- [ ] 沙箱路径校验处理了符号链接和`..`穿越
- [ ] 沙箱配置路径硬编码为只读
- [ ] 危险命令模式（pipe、redirect、delete）被解析和拦截
- [ ] 网络隔离：默认阻断，白名单域名显式声明
- [ ] 审计日志不可由Agent修改或删除
- [ ] 凭证外置：Agent通过`credentials_request`获取，不持有原始凭证
- [ ] MCP第三方工具默认`always_ask`
- [ ] `settings.json` 和 `.claude/`目录Agent不可写
- [ ] deny > settings rules > hook allow 不可变量在所有代码路径成立

---

## 常见陷阱

### 陷阱1：Hook allow覆盖了deny规则

**症状**：用户在settings中deny了某操作，但Hook中写了allow逻辑，结果操作被执行。

**根因**：Hook执行在deny检查之前，或deny检查不完整。

**解决**：在Hook系统中植入优先级守卫——任何Hook返回`allow`前，必须先检查当前规则引擎判定。如果规则引擎结果为`deny`，Hook的`allow`被静默忽略。这是不可变量，应在`HookSystem.execute_pre`的入口处用`assert`或等价机制守卫。

### 陷阱2：Agent通过符号链接逃逸沙箱

**症状**：Agent创建符号链接指向宿主机`/etc/`，然后通过链接读写敏感文件。

**解决**：`validate_path`必须在解析符号链接后再判定。使用`realpath`（POSIX）或等价API。对于不支持符号链接的沙箱技术（如bubblewrap），在启动时通过内核参数禁止符号链接创建。

### 陷阱3：Agent关闭沙箱自身

**症状**：Agent通过write工具修改`settings.json`中沙箱配置，然后重启会话绕过隔离。

**解决**：沙箱配置路径硬编码在编译期常量中。在工具层面对这些路径做write拦截——硬编码deny规则，用户不可配置关闭。启动时对`settings.json`做只读挂载（Docker: `--read-only`标签，bubblewrap: 不给予写权限）。

### 陷阱4：YOLO过度放行

**症状**：AI分类器将高危操作误判为低风险，导致自动执行危险命令。

**解决**：YOLO必须设置保守的分类阈值。分类器输出`unknown`时绝不自动放行。每次YOLO决策记录在审计日志中，包含分类依据和置信度，用于事后审查和分类器调优。

### 陷阱5：MCP工具绕过权限检查

**症状**：第三方MCP工具以信任模式注册，LLM调用时未经过权限检查。

**解决**：MCP工具注册时默认`level: ask`。MCP协议适配层必须在转发工具调用前调用`PermissionManager.check_permission`，走完完整规则链。不可因为"MCP提供者是可信的"而跳过检查——信任必须显式配置。

### 陷阱6：凭证泄露到沙箱日志

**症状**：API Key出现在命令参数中，被审计日志记录成明文。

**解决**：凭证外置架构——凭证不进入沙箱，不进入命令行参数。`credentials_request`返回的是一次性环境变量注入，日志中自动脱敏为`[REDACTED]`。PostToolUse Hook中增加输出脱敏扫描，匹配常见token模式自动替换。

---

## 下一步

完成Phase 6后，进入 **Phase 7: 生产化**（参考 `references/07-phase-production.md`）。

---

# 安全护栏子循环 (v4)

> 配合 Phase 4 的 Loop Engineering 升级，在每个 Agent 行动前后嵌入轻量安全检查循环，形成"行动前审核 → 行动后审计"的双层防线。

## 设计原理

安全护栏子循环在主 Agent 循环的每个行动（工具调用）前后各插入一个检查点：
- **Pre-Action Check**：行动前验证权限、预算、合规、速率限制
- **Post-Action Audit**：行动后扫描敏感信息泄露、PII、输出合规

## 抽象接口

```python
from enum import Enum
from dataclasses import dataclass
from typing import Callable, Dict, List, Any


class SafetyVerdict(Enum):
    """安全判定结果"""
    ALLOW = "allow"                    # 放行
    BLOCK = "block"                    # 阻断 + 告警
    REQUIRE_REPLAN = "require_replan"  # 要求 Agent 重新规划
    REDACT = "redact"                  # 自动脱敏后继续


@dataclass
class SafetyRule:
    """安全规则定义"""
    name: str
    description: str
    severity: str  # critical | high | medium
    check_fn: Callable


class SafetyGuardLoop:
    """
    安全护栏子循环：
    - 行动前：权限、预算、合规、速率限制检查
    - 行动后：敏感信息扫描、PII 检测、输出审核
    """

    def __init__(self):
        self.pre_rules: List[SafetyRule] = []   # 行动前规则列表
        self.post_rules: List[SafetyRule] = []  # 行动后规则列表
        self.safety_log: List[Dict] = []        # 安全事件日志

    async def pre_action_check(self, action: Dict, agent_state: Dict) -> SafetyVerdict:
        """行动前安全检查循环：遍历所有 pre_rules，任一 BLOCK 则阻断"""
        for rule in self.pre_rules:
            verdict = await rule.check_fn(action, agent_state)
            if verdict == SafetyVerdict.BLOCK:
                return SafetyVerdict.BLOCK
            if verdict == SafetyVerdict.REQUIRE_REPLAN:
                return SafetyVerdict.REQUIRE_REPLAN
        return SafetyVerdict.ALLOW

    async def post_action_audit(self, action: Dict, output: str) -> SafetyVerdict:
        """行动后审计循环：遍历所有 post_rules，REDACT 自动脱敏"""
        for rule in self.post_rules:
            verdict = await rule.check_fn(output)
            if verdict == SafetyVerdict.BLOCK:
                return SafetyVerdict.BLOCK
            if verdict == SafetyVerdict.REDACT:
                output = await self._redact(output, rule.name)
        return SafetyVerdict.ALLOW
```

## 预置规则集

### Pre-Action 规则（行动前）

| 规则 | 严重级别 | 说明 |
|------|---------|------|
| `block_destructive` | critical | 阻断对关键路径的破坏性操作（`/etc/`, `C:\Windows\`, `.git/`, `production/`） |
| `budget_limit` | high | 检查行动是否超出预算上限（定义与降级链见上文「预算与成本控制」） |
| `permission_check` | critical | 验证 Agent 对该操作的权限 |
| `rate_limit` | high | 检查 API 调用频率限制 |

### Post-Action 规则（行动后）

| 规则 | 严重级别 | 说明 |
|------|---------|------|
| `no_secrets` | critical | 扫描输出中的 API Key / Token / 密码 |
| `pii_detection` | critical | 检测个人身份信息（SSN / 信用卡号 / 邮箱） |
| `output_size` | medium | 验证输出大小在限制内 |
| `compliance` | high | 对照合规策略检查输出内容 |

## 安全护栏子循环与既有 6 层模型的映射

> v4 不引入第二套层编号。下方「6 层模型在 v4 技术下的映射表」把安全护栏子循环的能力挂到主文体定义的 Layer 1–6 上，避免双层编号打架。主文体 6 层定义见上文「纵深防御架构」（Layer 1 权限模型 → Layer 6 硬编码拒绝）。

| 安全护栏子循环组件 | 命中的既有层 | 说明 |
|---|---|---|
| Pre-Action: `permission_check` | Layer 1 权限模型 | 行动前重新走 Layer 1 规则链，deny 优先级不可变量 |
| Pre-Action: `budget_limit` | 预算与成本控制（权限第四维度，见上文） | 行动前校验 cost-per-task 是否突破 Budget |
| Pre-Action: `block_destructive` | Layer 6 硬编码拒绝 | 关键路径破坏性操作直接 BLOCK |
| Pre-Action: `rate_limit` | 跨层（Layer 1 之上） | API 频控，独立于权限但同处 Pre-Action |
| Post-Action: `no_secrets` / `pii_detection` / `compliance` | Layer 5 审计日志 | 行动后扫描并写入审计，命中则 REDACT/BLOCK |
| 整个子循环 | 跨 Layer 1 ↔ Layer 5 的检查点 | 不是新层，而是挂在主循环每个行动前后的检查点 |

**与 Layer 2（AI 分类器）的差异**：Layer 2 是静态规则链（"这个操作能否执行"），安全护栏子循环是动态上下文感知（"在当前状态下，这个操作是否安全"），二者都挂在 Layer 1 的不可变量之下，不另立层号。

**A3 联动（安全默认值，保守方向）**：安全护栏 / Hook 超时**默认降级为 DENY**（或升级为人工审批），不得 ALLOW，以守住 Layer 1 硬编码 deny 不可被绕过的铁律。permission deny（含 Layer 1 硬编码拒绝与 settings deny）属于不可自动恢复错误，**不进入 REPLAN 的可自动重试集合**；错误分类权威定义见 `references/08-core-concepts.md`。

## 规模适配

- **Minimal**：基础安全检查点（命令黑名单 `["rm", "drop", "delete"]`）。
- **Professional**：简化版 SafetyGuardLoop（pre-action 权限检查 + post-action 敏感信息扫描）。
- **Enterprise**：完整双层防线（4 条 pre-action 规则 + 4 条 post-action 规则 + 安全事件日志 + 告警通知）。

## AI 构建提示

```
根据用户选择的规模实现安全护栏子循环：

Professional 级别：
  1. 实现 SafetyGuardLoop 类，包含 2 条 pre-action 规则和 2 条 post-action 规则
  2. pre-action: permission_check + block_destructive
  3. post-action: no_secrets + pii_detection
  4. 集成到 AgentCore.run() 中：每个工具调用前后调用

Enterprise 级别：
  1. 实现完整 SafetyGuardLoop 类，包含全部 8 条规则
  2. 实现安全事件日志（safety_log），记录每次检查的判定结果
  3. 实现告警通知（_alert 方法，推送到 Slack / PagerDuty）
  4. 实现自动脱敏（_redact 方法，正则替换敏感内容为 [REDACTED]）
  5. 安全事件日志定期写入 WAL，支持审计回溯

关键约束：
  □ 安全护栏检查（含 Hook 拦截）不得阻塞主循环超过 50ms——**超时默认降级为 DENY（或升级为人工审批），不得 ALLOW**，以守住 Layer 1 硬编码 deny 不可被绕过（见上方「A3 联动」）
  □ 敏感信息扫描使用正则匹配，不调用 LLM（避免 Token 开销）
  □ BLOCK 判定必须记录完整的审计日志（action / rule / verdict / timestamp）
  □ 安全规则支持热更新（从配置中心加载，不重启 Agent）
  □ permission deny 不进入 REPLAN 可自动重试集合（错误分类见 references/08-core-concepts.md）
```