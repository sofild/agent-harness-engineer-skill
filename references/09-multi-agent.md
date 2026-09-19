# 多智能体协作

## 设计原理

### 为什么需要多 Agent 协作？

单 Agent 的三重瓶颈：
- **上下文窗口有限**（200K tokens）：单 Agent 处理多文件项目探索时，文件内容 + 工具结果快速填满窗口
- **认知负载饱和**：任务复杂度超过一定阈值后，Agent 开始"迷失"——跳过步骤、遗忘约束、产出质量下降
- **无并行能力**：线性的 read → think → act 循环无法利用并行资源

多 Agent 协作的本质是**分治策略**——将复杂任务拆解为独立子任务，分配给多个子 Agent 并行处理，最后综合结果。

### 子 Agent 上下文隔离设计（核心机制）

**为什么必须隔离上下文？**

如果子 Agent 共享父 Agent 的完整消息历史，每个子 Agent 都携带 100K+ tokens 的历史包袱。10 个子 Agent × 100K tokens = 1M tokens 的上下文开销，经济上不可行，认知上不可维护。

**上下文隔离机制：**

```
┌──────────────────────────────────────────────────────┐
│  父 Agent (Coordinator)                              │
│  messages: [sys_prompt, ..., user_task]  (30K tokens)│
│                                                      │
│  接收到子 Agent 结果：summary (500 tokens) ← 不是原始数据 │
├──────────────────────────────────────────────────────┤
│                                                      │
│  ┌─────────────────┐  ┌─────────────────┐            │
│  │ 子 Agent A      │  │ 子 Agent B      │            │
│  │ messages: []    │  │ messages: []    │  ← 空白启动│
│  │ + sys_prompt    │  │ + sys_prompt    │            │
│  │ + subtask_A     │  │ + subtask_B     │            │
│  │ (total ~8K)     │  │ (total ~8K)     │            │
│  │                 │  │                 │            │
│  │ 结果 → summary  │  │ 结果 → summary  │            │
│  └─────────────────┘  └─────────────────┘            │
└──────────────────────────────────────────────────────┘
```

**Token 节省量化分析（10 文件探索场景）：**

```
场景：探索 10 个文件，每个文件约 2000 行

方案 A（无隔离，单 Agent）：
  读取 10 个文件 → 10 × ~5K tokens 工具输出 = 50K tokens
  全部保留在上下文中 → 累积在消息列表中
  总上下文占用：~50K tokens（仅文件内容）

方案 B（上下文隔离，多 Agent）：
  10 个子 Agent，各处理 1 个文件
  每个子 Agent 上下文：~5K（sys_prompt + 1 个文件）
  每个子 Agent 返回摘要：~200 tokens
  父 Agent 收到的总摘要：10 × 200 = 2K tokens
  总上下文占用：~2K tokens（父 Agent 视角）

节省率：(50K - 2K) / 50K = 96%
```

**启动开销量化：**
每个子 Agent 需要独立加载 system prompt → 约 5-10K tokens/子 Agent。在 10 文件场景下，10 个子 Agent × 8K 系统提示 = 80K 系统提示总开销。但系统提示通过 **prompt cache** 命中（前缀稳定），实际 API 计费 token 远低于此值。

**关键设计约束：**
- 子 Agent 从空白 `messages` 列表启动，不继承父 Agent 的任何对话历史
- 子 Agent 完成后，**只向父 Agent 返回摘要**（结构化 summary），不返回原始工具输出或完整对话
- 父 Agent 看到的是压缩后的信息——这意味着父 Agent 的决策质量取决于摘要质量

---

## Worktree 隔离机制

子 Agent 的文件系统隔离通过 Git worktree 实现。这是多 Agent 协作中保证文件操作安全的关键机制：

```
宿主机文件系统：
  /project/
    ├── .git/                  ← 共享 Git 仓库
    ├── main/                  ← 主 worktree（父 Agent 工作区）
    └── worktrees/
        ├── agent-a/           ← 子 Agent A 的隔离 worktree
        │   └── (从 main 检出)
        ├── agent-b/           ← 子 Agent B 的隔离 worktree
        │   └── (从 main 检出)
        └── agent-c/           ← 子 Agent C 的隔离 worktree
            └── (从 main 检出)
```

**隔离特性：**
- 每个子 Agent 拥有独立的文件系统视图——对文件的修改互不干扰
- Git worktree 保证分支隔离：子 Agent A 的 commit 不会污染子 Agent B 的工作区
- 子 Agent 完成后，worktree 中的变更通过 PR/branch 形式合并回主 worktree
- 沙箱与 worktree 组合：子 Agent 的沙箱根目录即为其 worktree 路径，无法访问其他 worktree

**生命周期：**
```
创建：parent spawns sub-agent → `git worktree add worktrees/agent-N`
执行：sub-agent operates within worktree/agent-N
提交：sub-agent returns summary + `git diff` to parent
清理：parent evaluates → `git worktree remove worktrees/agent-N`
```

---

## Coordinator 模式（中心化协调）

### 任务分解算法（抽象设计，非可执行代码）

Coordinator 的核心职责是将复杂任务分解为可并行执行的独立子任务。分解质量直接决定多 Agent 协作的效率和结果质量。

**任务分解策略：**

```
算法：Coordinator.decompose(complexTask) → List[SubTask]

阶段 1 —— 依赖分析
  ├── 构建任务依赖图 DAG
  │   ├── 顶点 = 任务单元（文件、模块、功能点）
  │   └── 边 = 依赖关系（A 的输出是 B 的输入）
  ├── 找出所有入度为 0 的顶点 → 第 1 批并行子任务
  └── 标记依赖链 → 顺序执行批次

阶段 2 —— 独立性判定
  ├── 判定条件：
  │   ├── 操作的文件集合是否无交集？
  │   ├── 结果是否可以独立验证？
  │   └── 是否需要其他子任务的中间产物？
  ├── 若满足全部条件 → 标记为独立子任务，可并行
  └── 若任一条不满足 → 标记为依赖子任务，需顺序执行

阶段 3 —— 粒度控制
  ├── 过粗：单个子任务仍然超过 30K tokens 上下文 → 继续拆分
  ├── 过细：子任务 < 1K tokens → 启动开销 > 执行开销 → 合并
  └── 黄金粒度：每个子任务预估 5-15K tokens 上下文占用
```

**子 Agent 分配策略：**

```
算法：Coordinator.allocate(subtasks, agents) → Map<Agent, SubTask>

策略选项：
  A. 轮转分配（Round-Robin）
     - 适合：同构 Agent，子任务难度均匀
     - 复杂度：O(n)

  B. 启发式分配（Heuristic Matching）
     - 适合：异构 Agent（不同 skill/工具集）
     - 逻辑：为每个子任务匹配最合适的 Agent profile
     - 复杂度：O(n × m)，n=子任务数, m=Agent类型数

  C. 负载感知分配（Load-Aware）
     - 适合：子任务大小不均
     - 逻辑：预估每个子任务的 token 消耗，动态分配给最空闲的 Agent
     - 复杂度：O(n log m)（优先队列）
```

**结果综合策略：**

```
算法：Coordinator.synthesize(results) → FinalOutput

综合模式：
  模式 1 —— 拼接（Concatenation）
    - 使用场景：子结果互不重叠（如各模块的文档、各文件的测试）
    - 操作：按顺序拼接 → 格式统一 → 输出

  模式 2 —— 合并（Merge）
    - 使用场景：子结果有重叠域（如多个子 Agent 改同一文件的不同部分）
    - 操作：diff 合并 → 冲突检测 → 人工或自动解决冲突

  模式 3 —— 总结（Summarization）
    - 使用场景：子结果信息量大，需提炼核心发现
    - 操作：LLM 通读所有子结果 → 生成综合报告 → 标注各发现的来源

  模式 4 —— 验证后合并（Verify-then-Merge）
    - 使用场景：子结果需要交叉验证（如一个 Agent 生成代码，另一个生成测试）
    - 操作：运行验证 Agent → 检查一致性 → 若失败则重新调度
```

---

## Swarm 模式（去中心化协调）

### Coordinator vs Swarm 对比

| 特性 | Coordinator | Swarm |
|------|-------------|-------|
| 控制方式 | 中心化（一个协调者分配任务） | 去中心化（Agent 间对等通信） |
| 通信方式 | 主从（Parent → Child） | 对等（Peer-to-Peer 消息广播） |
| 任务分配 | 协调者主动分解和分配 | Agent 自行根据消息选择任务 |
| 适用场景 | 任务可预先分解（结构化任务） | 任务边界模糊（探索性任务） |
| 复杂度 | 低——协调者逻辑是瓶颈 | 高——需要共识算法和冲突解决 |
| 结果质量 | 取决于协调者分解质量 | 取决于 Agent 间通信效率 |
| 可预测性 | 高——执行路径确定 | 低——涌现行为，难以预测 |
| 故障容错 | 低——协调者单点故障 | 高——无单点，Agent 可互相替代 |
| 建议规模 | 3-10 个子 Agent | 5-50 个 Agent |

### Swarm 设计要点（抽象设计，非可执行代码）

**通信模型：**

```
Agent 间通信通过消息总线（Message Bus）实现：
  ├── 每条消息包含：sender_id, recipient_id（可为广播）, content, priority, ttl
  ├── 消息类型：TaskProposal, TaskClaim, ResultShare, ConflictAlert, ConsensusVote
  └── 消息持久化：总线保证消息不丢失，Agent 离线期间消息排队

共识机制（简化 Raft 风格）：
  ├── 提议阶段：任一 Agent 提出任务分配方案
  ├── 投票阶段：其他 Agent 对方案投票（accept/reject）
  ├── 达成条件：超过半数 Agent 在 TTL 内接受
  └── 超时处理：若超时未达成 → 随机退避后重新提议
```

**Swarm 适用性约束：**
Swarm 模式在以下条件同时满足时才优于 Coordinator：
1. 任务无法预先分解（子任务边界在执行中涌现）
2. Agent 数量 > 5（并行度需要去中心化调度）
3. 对结果的可预测性要求较低（接受探索性输出）
4. 通信开销（消息传递 tokens）相对于执行开销可忽略

---

## 规模适应性指南

### Minimal（最小可行）

多 Agent 协作不适用于 Minimal 规模——此规模下 Agent 本身的能力有限，上下文隔离和 worktree 的复杂度远超收益。**建议跳过**，用单 Agent 顺序处理。

### Professional（专业级）

- 实现 Coordinator 模式：任务分解 + 子 Agent 分配 + 结果综合
- 子 Agent 数量：3-5 个
- 上下文隔离：子 Agent 空白启动 + 摘要返回
- 不需要 Worktree：子 Agent 操作同一工作区但不同文件（通过文件级锁协调）
- 通信：函数调用（同进程内），无消息总线
- 代码量：~500-800 行

### Enterprise（企业级）

- 全功能实现：Coordinator + Swarm 双模式，按任务特征自动切换
- 子 Agent 数量：5-50 个，支持动态扩缩
- Worktree 隔离：每个子 Agent 独立 Git worktree + Docker 沙箱
- 消息总线：异步消息队列，支持 Agent 离线排队
- 共识算法：完整实现，含投票超时和冲突解决
- 监控：每个子 Agent 的 token 消耗、执行时间、成功率实时看板
- 代码量：~2000-3500 行

---

## 常见陷阱与失效模式

### 陷阱 1：子 Agent 上下文膨胀

**症状**：父 Agent 将完整对话历史注入子 Agent 的初始消息中，"为了方便子 Agent 理解背景"。

**后果**：10 个子 Agent 各带 100K 历史 → 1M tokens 上下文浪费。96% 的隔离收益消失。

**解决**：子 Agent 初始 messages 必须为空数组。仅通过 subtask 描述传递必要信息。如果 subAgent 需要历史上下文，父 Agent 应在分解 subtask 时主动提取相关信息塞入 subtask 描述。

### 陷阱 2：摘要信息丢失

**症状**：子 Agent 返回的摘要过于粗略（"检查完毕，没问题"），关键发现被丢弃。

**根因**：没有强制执行摘要结构。

**解决**：定义 Summary 的结构化 Schema（findings、files_modified、errors、suggestions 为必填字段）。在子 Agent 的系统提示中明确要求按 Schema 输出。Coordinator 在综合前校验 Schema 完整性——不完整的摘要退回子 Agent 重做。

### 陷阱 3：Task 分解粒度过细

**症状**：Coordinator 将"修改一个函数"拆成 5 个子任务，每个子 Agent 只改 3 行代码。

**后果**：子 Agent 启动开销（~8K tokens 系统提示）远超执行开销。Token 效率反而低于单 Agent 处理。

**解决**：每个子任务至少 5K tokens 预估上下文占用。低于此阈值的子任务应合并。

### 陷阱 4：Worktree 泄漏

**症状**：子 Agent 创建了 worktree 但 Coordinator 未能清理，磁盘上残留大量孤立 worktree。

**解决**：在 Coordinator 的 `finally` 块中执行 worktree 清理（类似 RAII 模式）。启动时先扫描 `worktrees/` 目录并清理上次会话的残留。

### 陷阱 5：Swarm 共识死锁

**症状**：Swarm 模式下，Agent 在投票阶段永远无法达成过半共识——每个 Agent 坚持自己的方案。

**解决**：设置最大投票轮次（3 轮）。超轮次后，随机选择一个 Agent 方案作为最终方案（Dictator Fallback）。或改用 Coordinator 模式降级。

---

## AI 构建提示

构建多 Agent 协作系统时，AI 不应直接复制代码，而应根据以下提示自行实现：

1. **先建抽象接口**：
   - `SubAgent` 接口：`execute(subtask, context) → Summary`。不接受完整消息历史。
   - `Coordinator` 接口：`decompose(task) → SubTask[]` → `allocate(subtasks, agents) → Assignments` → `synthesize(summaries) → Result`
   - `MessageBus` 接口（Swarm 用）：`publish(msg)`, `subscribe(pattern)`, `consume()`

2. **上下文隔离是硬约束**：子 Agent 构造函数不接受 messages 参数。子 Agent 内部自行构建消息列表，系统提示从模板注入。

3. **摘要格式标准化**：子 Agent 返回的摘要必须有固定结构——至少包含 `{findings, files_modified, errors, suggestions}` 字段。无结构摘要会导致综合阶段解析失败。

4. **Task decomposition 使用 LLM 辅助**：不要让 Coordinator 硬编码分解逻辑。将任务描述输入 LLM，要求输出结构化子任务列表（含依赖关系），然后 Coordinator 做 DAG 构建和并行调度。

5. **错误隔离**：一个子 Agent 失败不应阻塞其他子 Agent。Coordinator 收集所有子 Agent 结果后，对失败的任务决定：重试 / 替代方案 / 跳过并标记。

6. **测试策略**：
   - 单元测试：decompose → 验证子任务独立性（文件无交集）、synthesize → 验证摘要结构完整性
   - 集成测试：3 个子 Agent 并行处理同一项目的不同模块 → 验证 worktree 隔离（A 的修改不影响 B）、验证结果综合正确

7. **Worktree 实现**：通过 `git worktree` CLI 创建隔离工作区。子 Agent 的 `workdir` 指向其 worktree 路径。完成后由 Coordinator 执行 `git worktree remove` 清理。若子 Agent 在 worktree 中产生了有价值的变更，Coordinator 先 `git merge` 或创建 branch 再清理。

8. **Swarm 模式的共识算法**使用"轻量 Raft"——不实现完整的日志复制，只实现 Leader 选举和提议投票。Agent 数量通常 < 50，不需要完整的分布式共识协议。

---

# 多 Agent 拓扑循环 (v4)

> 配合 Phase 4 的 Loop Engineering 升级，引入四种标准的多 Agent 协作拓扑（含 Evaluator 与对抗式验证），形成可组合的"协作循环"。

## 设计原理

单个 Agent 的循环效能有天花板——推理深度、上下文窗口、单一视角都有不可逾越的局限。多 Agent 拓扑循环将多个 Agent 嵌套在一个更大的循环中，形成结构化协作。

## 四种标准拓扑（含 Evaluator 与对抗式验证）

> 选型总纲：**每个拓扑都是用额外 token 换更低的缺陷率**。是否值得，取决于"缺陷成本"——缺陷越贵（安全、关键决策、不可逆改动），越该上更重的拓扑。各拓扑的 **token 倍率与缺陷成本门槛** 见末尾「拓扑经济性对照表」（均为基于经验的估算，非实测基准）。

### 拓扑 1：Manager-Worker（管理者-工人）

主 Agent（Manager）分配子任务，启动子 Agent Loop 并等待结果，自身保持监督循环，随时中断或重新分配。

```python
class ManagerWorkerLoop:
    """
    Manager 自身运行一个监督循环：
    1. 分析任务，拆解为子任务
    2. 分配给 Worker（创建子循环）
    3. 收集结果，评估质量
    4. 不满意则重新分配（最多 3 次，评估标准见下方「重分配评估标准」）
    """

    def __init__(self):
        self.workers: Dict[str, WorkerAgent] = {}
        self.task_queue: asyncio.Queue = asyncio.Queue()

    async def manage(self, main_task: str) -> AsyncGenerator[AgentEvent, None]:
        """Manager 的主循环"""
        # Step 1: 拆解任务
        # Step 2: 分配循环（支持重分配）
        # Step 3: 质量评估
        # Step 4: 不满意则重新分配（最多 3 次，见下方评估标准）
        ...
```

**重分配评估标准（最多 3 次改派，避免无限空转）**

Manager 不能在"感觉不对"时就重分配——必须有可判定的标准，否则会陷入改派循环。三档判定如下：

| 判定维度 | 算失败（触发重分配） | 什么情况下改派（换 Worker） | 什么时候升级人工（`human_required`） |
|---------|---------------------|----------------------------|--------------------------------------|
| 输出正确性 | 子任务产物未通过确定性验证（compile/lint/test 失败，见 `references/04-phase-agent-loop.md` 的 CONTINUE-SITE-8） | 同一 Worker 第 1–2 次产出不合格，但其 profile 与该子任务匹配 → 清空上下文重试，给一次修正机会 | 同一子任务 **连续 3 次** 重分配后仍不达标 → 不再改派，标记 `human_required`，交人工 |
| 范围契合度 | 产物解决了错误子任务（偏离 subtask 描述） | 子任务描述本身有歧义 → 回到 Step 1 重新拆解并改派，而非惩罚 Worker | 重分配耗尽且拆解已澄清仍失败 → 升级人工复查任务规格 |
| 资源/超时 | 单次 Worker 执行超过预算阈值（token 或 wall-clock） | 换用更轻量 profile 的 Worker 重试 | 预算内无法完成 → 升级人工决定是否拆分/降标 |

**关键约束**：
- 重分配计数 **按子任务独立**——一个子任务失败不影响其他子任务的分配额度。
- 每次重分配前必须先把**结构化失败定位**（文件路径 + 行号 + 错误码，来自 Verifier 的 `machine_readable_output`）作为新 subtask 的上下文注入，而不是"再做一次"。
- 第 3 次失败后**禁止自动重试**——必须走 `human_required`，否则违反「不自评」与「不空转」铁律（连续失败说明任务规格或能力边界问题，Agent 无法自愈）。

### 拓扑 2：Generator-Critic（生成-批评-修正）

输出 Agent 生成 → 批评 Agent 指出问题 → 生成 Agent 再次修改。形成一个内环迭代，直到质量过关。

```python
class GeneratorCriticLoop:
    """
    内环结构：
    Generator → Critic → [PASS score>=0.9] → 输出
                       → [FAIL] → Generator（带批评意见）→ ...
    """

    async def generate(self, task: str, max_rounds: int = 5) -> AsyncGenerator[AgentEvent, None]:
        """生成-批评-修正主循环"""
        output = await self._generator(task)
        for round_num in range(max_rounds):
            critique = await self._critic(output, task)
            if critique["score"] >= 0.9:
                yield FinalResponseEvent(text=output)
                return
            output = await self._generator(task, previous_output=output, feedback=critique["feedback"])
        yield FinalResponseEvent(text=output)
```

**Critic 构造约束（与拓扑 4 Evaluator 统一口径）**

Generator-Critic 的 Critic 不是"另一个会聊天的 Agent"，而是与 Evaluator 同构的**独立校验者**。两处口径必须一致，避免 AI 在两套规则间摇摆：

- **temperature 固定 0.0–0.1**：Critic 做确定性评分，不做创造性发散；与 Evaluator 的 rubric 打分共用同一温度区间。
- **独立上下文**：Critic 不继承 Generator 的消息历史（看不到 Generator 的推理过程），从空白 `messages` 启动，只接收 `output` + `task` 作为评估输入——这正是 Evaluator 约束 ①。
- **结构化输出**：`{score, feedback, evidence}`——`score` 用于 PASS/FAIL 判定（阈值建议 ≥0.9），`feedback` 回喂 Generator，`evidence` 给出扣分依据（与 Evaluator 的 evidence/counter-proposal 同构）。
- **禁止 self-verify**：Critic 与 Generator 必须是两个独立 Agent 实例，Generator 不得调用自身的 `_critic` 给自己打分。

> 与 Evaluator 的差别仅在于**循环位置**：Critic 嵌在生成-修正内环里反复迭代，Evaluator 是一次性独立评审（见拓扑 4）。二者共享"独立上下文 + 低温度 + rubric + 结构化输出"的底层构造。

### 拓扑 3：Debate（多 Agent 辩论）

多个 Agent 并行独立回答，然后互相辩论多轮，最后裁判 Agent 汇总。

```python
class DebateLoop:
    """
    辩论流程：
    1. 多个 Expert Agent 并行独立回答
    2. 互相审阅对方的回答，提出反驳
    3. 多轮辩论后，Judge Agent 汇总裁决
    """

    async def debate(self, question: str, num_experts: int = 3, rounds: int = 3) -> AsyncGenerator[AgentEvent, None]:
        """辩论主循环"""
        # Round 1: 独立回答
        # Round 2-N: 互相辩论
        # 最终裁决
        ...
```

### 拓扑 4：Evaluator（独立评估子 Agent）★v4 新增

**何时读本节**：当你发现「让 coding agent 复查自己的输出，它会用写出那个 bug 时同样的流畅自信给自己打及格」这一问题时，用本节把评估者强制独立出来。本节对应 `references/04-phase-agent-loop.md` 中 Verifier 的「推断型」分支——但 04 的 Verifier 主体是**计算型**（compile/lint/test），Evaluator 是**推断型**（无法代码化的主观维度），二者分工见下方「与 04 确定性验证的分工表」。

**技术依据（为什么必须独立）**

Agent 一致性高估自己的产出，尤其在主观任务上——让它复查自己的输出，它会用写出 bug 时同样的流畅自信给自己打及格。Anthropic 的解法是把 **Planner（把意图展开为规格）→ Generator（实现）→ Evaluator（用 few-shot 校准过的评分标准打分）** 强制分离。**Evaluator 不持有 Generator 的推理记忆、对它的选择没有投入、有 rubric 而非感觉**——"这是被重建为结构的 code review"。代价是每个工作单元多跑一个 Agent，是否值得取决于缺陷成本。实测对照：solo agent 做复古游戏机项目花了 9 小时但失败；加上 Evaluator 子 agent 的完整 harness 跑了 6 小时，产出了可工作的软件。

**四条构造约束（硬性，缺一不可）**

```
┌──────────────────────────────────────────────────────────────┐
│  Evaluator 子 Agent（独立上下文，从空白 messages 启动）         │
│                                                              │
│  输入：artifact（Generator 产物）+ rubric + few-shot 样本       │
│        ❌ 不接收 Generator 的对话历史 / 推理轨迹               │
│                                                              │
│  处理：按 rubric 维度逐项打分（含阈值）                         │
│        对照 few-shot 校准「这一档大概长什么样」                  │
│                                                              │
│  输出：{                                                     │
│    score:        各维度得分（0-1 或等级）                     │
│    evidence:     每条扣分的定位与依据（文件/行/段落）          │
│    counter_proposal: 若不及格，给出"应该怎么改"的反提案       │
│  }                                                           │
└──────────────────────────────────────────────────────────────┘
```

- **约束 ① 独立上下文**：Evaluator 不继承 Generator 的消息历史，从空白 `messages` 启动，只接收 `artifact` + `rubric` + `few-shot` 作为评估输入。它看不到 Generator"为什么这么写"，因此没有沉没成本带来的偏袒。
- **约束 ② 显式 rubric**：评分标准必须前置定义，含**评分维度**（如正确性、可读性、架构契合、安全语义）与**每维度的阈值/档位**（如 `correctness ≥ 0.8 且 security == pass` 才算合格）。没有 rubric 的"I'll review it"只是换个角度的自评。
- **约束 ③ few-shot 校准样本**：在系统提示中放 2–4 个「输入片段 + 期望评分 + 期望证据」的范例，把"这一档大概长什么样"锚定下来，降低评分方差，让 Evaluator 与人工评审标准对齐。
- **约束 ④ 输出结构**：必须输出 `score + evidence + counter_proposal` 三元组——`score` 供 PASS/FAIL 判定，`evidence` 给出可定位的扣分依据，`counter_proposal` 在不及格时直接给出修正方向（避免只说"不行"却不给路）。

```python
class EvaluatorAgent:
    """
    独立评估子 Agent（推断型校验者）。

    架构约束（铁律）:
      - 不继承 Generator 的 messages 历史（约束①）
      - 系统提示内嵌 rubric（维度 + 阈值）与 few-shot 校准样本（约束②③）
      - 输出必须含 score / evidence / counter_proposal（约束④）
      - 与 Generator 是两个独立实例：禁止 self-evaluate
    """

    def __init__(self, rubric: Dict[str, Any], few_shot: List[Dict[str, Any]]):
        self.rubric = rubric          # 含维度与阈值
        self.few_shot = few_shot      # 校准样本
        # 注意：构造函数不接受 messages 参数（约束①）

    async def evaluate(self, artifact: Any, task: str) -> Dict[str, Any]:
        """
        对 Generator 产物做独立评分。

        Args:
            artifact: Generator 产出的 artifact（代码 / 设计 / 决策草稿）
            task:     原始任务描述（用于上下文对齐）

        Returns:
            {"score": {...}, "evidence": [...], "counter_proposal": "..."}
        """
        raise NotImplementedError("AI: 按 rubric 维度逐项打分，"
                                   "对照 few-shot 校准档位，输出 "
                                   "score + evidence + counter_proposal；"
                                   "不得读取 Generator 的推理历史")
```

#### 对抗式验证（Adversarial Verification）变体

Evaluator 的泛化形态：独立验证 Agent 被**明确提示去反驳一个发现，而非确认它**——它拿到的是"Generator 声称 X 成立"，任务是找出 X 不成立的证据，而不是验证 X 成立。这把「证实偏差」翻转成「证伪压力」。

```
常规 Evaluator:   拿到产物 → 评估"它好不好"      → 偏乐观（默认找通过理由）
对抗式验证:       拿到主张 → 任务"推翻这个主张"  → 偏悲观（默认找反例）
                  找不到反例 ⇒ 主张暂时站得住（负向确认）
```

**适用边界**

| 适合用对抗式验证 | 不适合用对抗式验证 |
|----------------|-------------------|
| 安全审计（找漏洞而非证明无漏洞） | 延迟敏感任务（多跑一个对抗 Agent 直接加倍延迟） |
| 设计评审（挑战架构假设的脆弱点） | 低缺陷成本任务（错别字、一次性脚本，重验证不值） |
| 关键决策（上线/回滚/选型，错一次代价高） | 产出可逆且易重做的小改动 |
| 任何「假阳性代价 < 假阴性代价」的场景 | 任何需要快速收敛的 exploratory 任务 |

**构造要点**：对抗式验证仍须遵守 Evaluator 四条约束（尤其①独立上下文、④输出反提案）。它的 `counter_proposal` 不是"怎么改"，而是"主张为何站不住 + 最小的证伪证据"。

### 与 04 确定性验证的分工表

Evaluator（推断型）与 `references/04-phase-agent-loop.md` 的 Verifier（计算型）不是竞争关系，而是**两级闸门**：先算后推，能算的不推。

| 维度 | 计算型验证（04 Verifier） | 推断型验证（09 Evaluator） |
|------|--------------------------|---------------------------|
| 判断者 | 编译器 / linter / test runner / schema validator | 独立 LLM 评估子 Agent |
| 代表检查 | compile / lint / type / unit / schema / 安全扫描 | 可读性、架构契合、安全语义、设计合理性 |
| 何时跑 | **优先且必须**——能代码化的先跑，便宜（毫秒~秒，近乎免费） | **仅当**该维度无法代码化时才跑，贵（多一次 LLM 调用） |
| 确定性 | 确定（同输入同结果） | 概率（需 few-shot 校准降低方差） |
| 是否最终评判 | 是（且应优先） | 否——只能作为辅助信号，不得单独放行 |
| 不自评约束 | Generator 不得 `self.verify()` 自己产物 | Generator ≠ Evaluator，两个独立实例 |
| 失败回喂 | `machine_readable_output`（文件+行+错误码）注入下一轮 | `score + evidence + counter_proposal` 注入下一轮 |

**分工铁律**：
1. **计算型优先**：能用 compile/lint/type/test 判定的，绝不交给 Evaluator——编译器自己知道结果，且确定、即时、免费。
2. **推断型补漏**：Evaluator 只处理计算型覆盖不到的**主观维度**，且不得作为唯一放行条件（须与计算型门禁叠加）。
3. **两者都不自评**：生成者既不能调自己的 Verifier，也不能当自己的 Evaluator——这是 04 与 09 共同遵守的硬约束。

## 拓扑选择指南

| 拓扑 | Token 倍率* | 质量提升 | 缺陷成本门槛（低于此不上该拓扑） | 适用场景 |
|------|-----------|---------|-------------------------------|----------|
| solo（基线） | 1x | 基准 | 低——可逆、易重做、错一次代价小 | 简单查询、一次性脚本、探索性任务 |
| Coordinator | 2–3x | 中 | 中——多文件但可并行验证 | 结构化可分解的大型任务 |
| Manager-Worker | 3–5x | 中 | 中高——分工错误代价明显 | 大型多文件任务，有明确分工 |
| Generator-Critic | ~2x | 高 | 中——主观质量维度（可读性/正确性） | 代码生成、文档写作 |
| 多 Agent 辩论 | 4–6x | 最高 | 高——多视角冲突会致命 | 安全审计、设计评审、关键决策 |
| Evaluator（附加） | +1.5–2x 附加于 Generator | 高（补漏） | 高——自评会系统性漏判 | 主观维度无法代码化、需独立评审 |
| 对抗式验证（附加） | +2–3x 附加于 Evaluator/Generator | 最高（证伪） | 最高——假阴性代价 > 假阳性 | 安全审计、关键决策、上线/回滚 |

\* Token 倍率为**基于经验的估算**（相对 solo 基线），非实测基准；具体数值随模型、子任务粒度、few-shot 长度浮动。Evaluator 与对抗式验证是**附加倍率**——它们叠在某个生成拓扑之上，而非独立运行。

### 拓扑经济性对照表（选型速查）

```
缺陷成本 ↑
  │  对抗式验证 / 辩论      ← 假阴性代价极高，值得多跑 2-3 个 Agent
  │  Evaluator
  │  Generator-Critic
  │  Manager-Worker / Coordinator
  │  solo
  └──────────────────────→ Token 倍率 ↑（经济成本）

黄金法则：选「刚好覆盖缺陷成本」的最轻拓扑。
  - 缺陷便宜 → solo 或 Coordinator 足够
  - 缺陷中等 → Generator-Critic / Manager-Worker
  - 缺陷昂贵且主观 → Evaluator / 辩论 / 对抗式
```

## 规模适配

- **Minimal**：不支持多 Agent 拓扑。单 Agent 自检（不强制 Evaluator，缺陷成本由人工兜底）。
- **Professional**：可选。通过 Coordinator 模式实现基础的 Manager-Worker；Generator-Critic 的 Critic 可作为轻量独立评审；Evaluator 仅用于关键产物。
- **Enterprise**：完整支持四种拓扑（Manager-Worker / Generator-Critic / Debate / Evaluator）。包含 Agent 池管理、拓扑选择器、动态 Worker 扩缩；Evaluator 与对抗式验证作为默认推断型门禁叠加在计算型验证之后。

### Evaluator / 对抗式验证 的三级规模差异

| 维度 | Minimal | Professional | Enterprise |
|------|:-------:|:-----------:|:----------:|
| Evaluator 是否启用 | 否（单 Agent 自检） | 可选，仅关键产物 | **默认启用**，叠加于计算型门禁后 |
| rubric 形式 | — | 内嵌简版（2–3 维度） | 完整 rubric（维度 + 阈值 + few-shot 校准） |
| 对抗式验证 | 否 | 否 | 安全审计 / 关键决策自动触发 |
| 输出回喂 | — | `score + evidence` 文本日志 | `score + evidence + counter_proposal` 结构化注入 + 聚合可观测 |
| 不自评约束 | 不强制 | 建议独立 reviewer | **强制**：Generator ≠ Evaluator，禁止 self-evaluate |

## AI 构建提示

```
根据用户选择的规模实现多 Agent 拓扑：

Enterprise 级别：
  1. 实现 ManagerWorkerLoop 类，支持子任务拆解和动态重分配（重分配最多 3 次，按子任务独立计数，失败标准见拓扑 1）
  2. 实现 GeneratorCriticLoop 类，Generator 使用高温度（0.7-0.9）；**Critic 使用低温度（0.0-0.1）且独立上下文**——Critic 从空白 messages 启动，不继承 Generator 历史，输出 {score, feedback, evidence}（与 Evaluator 统一口径）
  3. 实现 DebateLoop 类，支持可配置的 Expert 数量和辩论轮次
  4. 实现 EvaluatorAgent 类（拓扑 4），严格遵守四条构造约束：①独立上下文（构造函数不接受 messages）②显式 rubric（维度+阈值）③few-shot 校准样本 ④输出 {score, evidence, counter_proposal}
  5. 实现拓扑选择器：根据任务类型与缺陷成本自动选择合适拓扑（参考拓扑经济性对照表）
  6. 每个子 Agent 拥有独立上下文窗口（从空白消息列表开始）

关键约束：
  □ 子 Agent 不接受完整消息历史，只接受结构化子任务描述
  □ 子 Agent 返回结构化摘要（{findings, files_modified, errors, suggestions}）
  □ 一个子 Agent 失败不应阻塞其他子 Agent
  □ 子 Agent 间通过 Coordinator 通信，不直接交互
  □ Generator ≠ Critic ≠ Evaluator：三者必须是独立实例，禁止任何 self-verify / self-evaluate
  □ 计算型验证（compile/lint/test，见 references/04-phase-agent-loop.md）优先于 Evaluator；Evaluator 只补漏无法代码化的主观维度
```