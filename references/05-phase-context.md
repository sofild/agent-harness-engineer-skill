# Phase 5: 上下文管理

## 目标

设计四级压缩管道、会话WAL、记忆系统，在严格上下文约束下保障Agent持续执行能力。核心挑战：200K tokens看似充足，但一次复杂工具调用的结果可能轻易占用数万tokens，几轮对话后即触达上限。

---

# 设计原理

## 上下文即负债

每一次API调用的token消耗都是延迟和成本的直接映射。上下文不仅是"能记住多少"，更是"能跑多快"和"能跑多久"的组合约束。设计目标不是最大化上下文利用率，而是在保证任务正确性的前提下最小化冗余。

**核心洞察**：
- 一个120K token的结果中，80%的内容对后续决策无实际影响
- 工具输出越冗长，Agent越容易"迷失"，注意力被稀释
- 压缩的质量指标不是压缩率，而是压缩后的"任务可恢复性"

## 渐进式压缩的经济学

四级压缩的本质是成本阶梯：每一级仅在前一级不足时触发，避免"用大炮打蚊子"。**管道顺序经过实测重排——Mask 必须最先做**：它确定、免费、可逆，且工具输出正是 Agent 上下文增长的主要来源（一条 `read_file` / `bash` 结果可能轻松占用数万 token）。

| 级别 | 名称 | 成本 | 场景 |
|------|------|------|------|
| Level 1 | Mask（工具结果遮蔽/清除） | ~0ms, 0 API调用 | 工具输出过长——**首选，几乎每次都先做** |
| Level 2 | Snip（剪断最旧历史） | ~0ms, 0 API调用 | 历史累计过长 |
| Level 3 | Collapse（上下文折叠） | ~5ms, 0 API调用 | 历史对话冗余 |
| Level 4 | Autocompact（自动摘要） | ~2s, 1次API调用 | 前三者均不足 |

### 成本 / 收益 / 有损性对照表

| 级别 | 直接成本 | 收益 | 有损性 | 可逆性 |
|------|----------|------|--------|--------|
| Mask | 0（纯字符串） | 清除工具输出中段，释放最多 token；JetBrains 实测约 **52% 成本下降 + ~2.6% 解决率提升** | 低——保留头尾与 structured 结果，遮蔽中段日志 | 完全可逆（原消息保留，仅生成遮蔽视图） |
| Snip | 0 | 移除最旧历史，确定性高 | 中——注入摘要，丢失原文细节 | 半可逆（需重读原文件恢复） |
| Collapse | 0 | 折叠连续非关键消息为一条模板摘要 | 中——模板摘要丢细节 | 完全可逆（读时投射，原数组不改） |
| Autocompact | 1 次 LLM 调用（单次可消耗 ~180K input token） | 语义压缩整段历史 | 高——LLM 摘要必然丢信息，检索类任务尤敏感 | 不可逆（原文被替换） |

> **关键取舍：遮蔽优先于摘要。** JetBrains《The Complexity Trap》(arXiv 2508.21433) 对照数据：观察遮蔽带来约 52% 成本下降 + 约 2.6% 解决率提升；纯摘要省下同样的钱，却让轨迹最多变长 15%。**默认先遮蔽，靠实力才用摘要。**

---

# 抽象接口层

系统设计为三层架构：

```
AgentCore
  └─ CompressionPipeline   ← 编排四级压缩，暴露 compact() 入口
       ├─ MaskStrategy        ← Level 1：工具结果遮蔽/清除（首选）
       ├─ SnipStrategy        ← Level 2：剪断最旧历史
       ├─ CollapseStrategy    ← Level 3：上下文折叠（读时投射）
       └─ AutocompactStrategy ← Level 4：LLM 语义摘要
  └─ MemoryManager         ← 四分类记忆 + 外部 scratchpad 生命周期管理
       ├─ ShortTermStore    ← 内存中，本次会话
       ├─ LongTermStore     ← 文件/向量DB，跨会话
       └─ ScratchpadStore   ← 轻量文件，压缩无损安全网
  └─ SessionWAL            ← JSONL追加日志，可恢复
  └─ CompactionLedger      ← 每次压缩的归因台账（append-only）
```

**CompressionPipeline** 不直接修改 `messages` 数组。它接收 `CompressionRequest {messages[], tokenBudget, reason}`，返回 `CompressionResult {compressedMessages[], tokensFreed, levelUsed, recoveryHints[]}`。这保证"压缩"与"消息管理"解耦。

**MemoryManager** 不嵌入AgentCore。它通过 `MemoryContextLoader` 以插件方式注入：Core在构造API请求时，调用Loader获取当前情景相关的记忆块，Loader内部查询MemoryManager并返回经过优先级排序的结果。

---

# 压缩算法描述

本章节描述**算法逻辑**而非可执行代码。所有描述使用伪代码格式表示控制流和数据结构操作。

## 通用前提

所有压缩策略统一从 `tokenCounter` 模块获取精确token数（通过模型原生tokenizer，不依赖 `len(content)/4` 估算）。`tokenCounter.count(text)` 返回精确值，`tokenCounter.estimate(structuredMessage)` 返回含元数据的估算。

压缩触发条件：`currentTokens > budget * 0.60 ~ 0.70`（默认 0.65），且 `hasAttemptedReactiveCompact == false`（见陷阱章节）。

**为什么是 60-70% 而非 85%**：context rot 研究显示 200K 窗口的模型在约 50K token 处就开始可测量退化。在 85% 才触发意味着摘要器（Autocompact，本身就是一次 LLM 调用）自己已在退化区间里工作——摘要质量在最需要的时候最差。60-70% 留出足够 headroom，使 Autocompact 在模型尚可正常推理时完成。

**阈值取舍**：
- **下调（更激进，如 50%）**：更早压缩、摘要质量更高、单次压缩更便宜；代价是压缩更频繁、更多 LLM 调用、活跃上下文被压缩得更小。Anthropic Compaction API 最低可配 50,000 token 触发即此思路。
- **上调（更保守，如 85%）**：减少压缩次数、活跃上下文更大；代价是压缩在高退化区触发，摘要质量崩塌，且 85% 处留给压缩本身的空间极小（单次压缩可消耗 ~180K input token），易触发 `context_length_exceeded`。**85% 不对**——它把最贵的步骤放在模型最弱的时候。
- **默认 60-70% 是可辩护区间**：服务端默认更保守。Anthropic Compaction API 默认在累计输入 150,000 token 触发（可配最低 50,000）；Claude Code 在 200K 窗口约 95% 触发属客户端实现，不代表服务端最佳实践。

---

## Level 1: Mask（工具结果遮蔽 / 清除）

**何时读本节**：当你发现上下文被 `read_file` / `bash` 等工具输出撑爆，但对话历史并不长时——这是管道**首选**。

**目标**：对超长工具结果进行遮蔽或清除，只保留决策所需的结构化片段。它是管道第一个入口：确定、免费、可逆，且工具输出正是最主要的上下文增长源。

**是否触发**：消息数组中存在 `role == "tool"` 且 `tokenCount(content) > outputProfile.threshold` 的消息。满足即触发，无需等待预算阈值。

**复杂度**：O(M) 遍历消息。
**成本**：~0ms，纯字符串操作，0 网络 IO。

### 抽象接口

```
class MaskStrategy:
    """Level 1 压缩：工具结果遮蔽/清除。优先于一切其他压缩。"""
    def compress(self, request: CompressionRequest) -> Optional[CompressionResult]:
        raise NotImplementedError(
            "AI: 遍历 role==tool 的消息，按 meta.outputProfile 阈值（如 read_file=8000, bash=2000）"
            "对超长结果做头尾保留 / 字段提取 / 整体清除；"
            "标记 masked=True 防重复遮蔽；原消息保留仅生成遮蔽视图；"
            "返回 CompressionResult 或 None（无超长工具结果时）"
        )
```

### 算法（伪代码）

```
FUNCTION mask(messages, outputProfiles):
    freed ← 0
    FOR EACH msg IN messages WHERE msg.role == "tool":
        threshold ← outputProfiles[msg.tool].threshold
        contentTokens ← tokenCount(msg.content)
        IF contentTokens ≤ threshold:
            CONTINUE  ← 短结果无需处理

        ── 三种遮蔽模式，按工具类型选择 ──
        IF 工具为 "structured_output"（如 JSON 结果）:
            msg.view ← 仅保留 status / files_changed / error 等决策字段
        ELSE:
            headContent ← 取前 headTokens 个token
            tailContent ← 取后 tailTokens 个token
            midTruncated ← contentTokens - headTokens - tailTokens
            msg.view ← headContent + "... [中间 {midTruncated} tokens 已遮蔽] ..." + tailContent
        msg.meta.masked ← true
        freed ← freed + midTruncated
    RETURN (messages, freed)
```

**关键设计决策**：

- **遮蔽优先于摘要**：对照表与 JetBrains 数据（约 52% 成本下降 + ~2.6% 解决率提升）。先遮蔽，靠实力才用摘要。
- **头尾保留或字段提取**：开头含状态/概要，末尾含结论/错误，中段日志价值低；结构化结果直接提取决策字段。
- **阈值差异化**：由工具注册时的 `meta.outputProfile` 提供（`read_file`≈8000、`bash`≈2000）。
- **完全可逆**：原消息保留，仅生成遮蔽视图注入；`masked: true` 防重复遮蔽。

---

## Level 2: Snip（剪断最旧历史）

**何时读本节**：当 Mask 之后历史累计 token 仍逼近预算，且最旧片段对当前决策价值低时。

**目标**：移除消息历史中最旧的连续片段。
**是否触发**：Mask 执行后 `currentTokens` 仍 > `budget * 0.60~0.70`，且最旧连续 N 条非决策关键消息 token 总和 ≥ 目标释放量。

**复杂度**：O(1) 数组操作。
**成本**：~0ms，无网络 IO。

### 抽象接口

```
class SnipStrategy:
    """Level 2 压缩：剪断最旧历史。Mask 不足时才用。"""
    def compress(self, request: CompressionRequest) -> Optional[CompressionResult]:
        raise NotImplementedError(
            "AI: 取 messages 前 N 条使 token 总和 ≥ targetTokensToFree；"
            "注入 system 消息声明已剪断并附简短摘要；"
            "边界：N<5 或总数<10 时不剪断；返回 CompressionResult 或 None"
        )
```

### 算法（伪代码）

```
FUNCTION snip(messages, targetTokensToFree):
    oldestBlock ← 取 messages 前 N 条，使其 token 总和 ≥ targetTokensToFree
    remainder   ← messages[N:]

    injection ← {
        role: "system",
        content: "上下文已剪断。以下为已跳过的历史摘要：" +
                 生成 N 条消息的简要摘要（每条截取前80字符）
    }

    resultMessages ← [injection] + remainder
    tokensFreed   ← sum(tokenCount(oldestBlock))
    RETURN (resultMessages, tokensFreed)

    ── 边界条件 ──
    如果 N < 5: 不进行Snip（避免频繁微小剪断），返回原始消息
    如果 messages 总数 < 10: 不进行Snip，返回原始消息
```

**关键设计决策**：Snip 不静默删除——它注入一条 system 消息说明"已剪断"，让 LLM 感知上下文断裂点，否则 Agent 会困惑"之前的内容去哪了"。Snip 在 Mask 之后、作为管道第二入口。

---

## Level 3: Collapse（上下文折叠）

**何时读本节**：当历史中存在连续大量"非决策关键"消息（确认、闲聊、无 tool_call 的回复），需要无损回退地压扁时。

**目标**：通过"读时投射"将 N 条连续历史消息折叠为一条模板摘要消息，但不修改原始消息数组——仅在读取上下文时动态注入。
**是否触发**：消息数组包含连续 ≥20 条"非决策关键"消息（决策关键=tool_calls / plan 变更 / task status 变更；非关键=纯文本对话、确认、无 tool_call 的 assistant 回复）。

**复杂度**：O(N) 遍历折叠窗口。
**成本**：~5ms，字符串模板拼接。

### 数据结构

```
collapseStore: Map<Int, CollapseEntry>
  key: 折叠起始消息的索引
  value: {
    originalSpan: [startIdx, endIdx],
    collapsedTokens: Int,
    summary: String,           ← 手工模板，非LLM生成
    collapsedAt: Timestamp,
    originalTotalTokens: Int
  }
```

### 算法（读时投射）

```
FUNCTION applyCollapseProjection(messages, collapseStore):
    projected ← []
    i ← 0
    WHILE i < len(messages):
        entry ← collapseStore.get(i)
        IF entry IS NOT NULL:
            projected.append({
                role: "system",
                content: "── 折叠上下文（{entry.originalSpan[1]-entry.originalSpan[0]}条消息）──\n" +
                         entry.summary
            })
            i ← entry.originalSpan[1]  ← 跳过折叠区间
            CONTINUE
        projected.append(messages[i])
        i ← i + 1
    RETURN projected

FUNCTION generateCollapseSummary(messagesInSpan):
    ── 构建模板化摘要，不调用LLM ──
    summary ← ""
    FOR EACH msg IN messagesInSpan:
        IF msg.role == "user":
            summary ← summary + "用户: " + truncate(msg.content, 200) + "\n"
        ELSE IF msg.role == "assistant" AND msg有tool_calls:
            summary ← summary + "调用了工具: " + join(tc.name for tc in msg.tool_calls) + "\n"
        ELSE IF msg.role == "tool":
            summary ← summary + "工具结果(" + tokenCount(msg.content) + " tokens)\n"
        ELSE:
            summary ← summary + "消息(" + tokenCount(msg.content) + " tokens)\n"
    RETURN summary
```

**关键设计决策**：

- **不修改原数组**：Collapse 不改变 `messages` 数组，只在 `buildAPIRequest()` 阶段通过投射生成轻量版本。可回退——需完整历史调试时原文仍在。
- **去重检查**：折叠前检查 bloom filter，避免已折叠区间被重复折叠。

---

## Level 4: Autocompact（自动摘要）

**何时读本节**：当 Mask→Snip→Collapse 三级均不足以释放空间，且上下文已逼近 60-70% 触发线时——这是唯一涉及 API 调用的级别，最贵、最有损。

**目标**：调用 LLM 对整段对话历史进行语义摘要。仅在前三级均不足时触发。
**是否触发**：Mask/Snip/Collapse 全部执行后 `currentTokens` 仍 > `budget * 0.60~0.70`，且 `hasAttemptedReactiveCompact == false`。

**成本**：1 次完整 LLM 调用（单次可消耗 ~180K input token，本身计费）。

### 抽象接口

```
class AutocompactStrategy:
    """Level 4 压缩：LLM 语义摘要。最贵、最有损，最后才用。"""
    def compress(self, request: CompressionRequest) -> Optional[CompressionResult]:
        raise NotImplementedError(
            "AI: 从尾向头扫描定位最小压缩区间，保留最近消息；"
            "用 SCHEMA 模板（见下文）调用 LLM 生成摘要；"
            "注入带恢复指令的 system 消息；写入 CompactionLedger；"
            "断言 head 逐字节不变；返回 CompressionResult 或 None"
        )
```

### 算法（伪代码）

```
FUNCTION autocompact(messages, targetFreeTokens, llmClient):
    ── 第一步：从尾向头扫描定位最小压缩区间 ──
    compressionStart ← 0
    accumulatedTokens ← 0
    FOR i FROM len(messages)-1 DOWN TO 0:
        accumulatedTokens ← accumulatedTokens + tokenCount(messages[i])
        IF accumulatedTokens ≥ targetFreeTokens:
            compressionStart ← i
            BREAK
    IF compressionStart == 0:
        RETURN FAILURE("无法压缩足够空间")

    historicalMsgs ← messages[0:compressionStart]
    recentMsgs    ← messages[compressionStart:]
    IF len(recentMsgs) < 10:   ← 保留最近10条不压缩
        compressionStart ← max(0, len(messages) - 10)
        historicalMsgs ← messages[0:compressionStart]
        recentMsgs    ← messages[compressionStart:]

    ── 第二步：用 schema 化模板调用 LLM 生成摘要（见下）──
    summary ← llmClient.invoke(SCHEMA_PROMPT + 序列化(historicalMsgs))

    ── 第三步：构建恢复提示（注入到 head 之后，不得改写 head）──
    recoveryMessage ← {
        role: "system",
        content: "── 上下文压缩点（Autocompact）──\n" + summary +
                 "\n── 恢复指令 ──\n1. 继续执行未完成任务\n2. 必要时重读当前工作文件\n3. 工具上下文已在前置消息恢复"
    }
    resultMessages ← [recoveryMessage] + recentMsgs
    RETURN (resultMessages, tokenCount(historicalMsgs) - tokenCount(summary))
```

**关键设计决策**：

- **从尾到头扫描**：保证压缩"最旧且最不重要"的部分。
- **schema 化摘要**：见下方"Autocompact 摘要模板"，强制包含"已排除的方案及原因"，防止 Agent 重试死路。
- **恢复消息**：插入带恢复指令的 system 消息，明确告知"需从头恢复状态"；该消息必须追加在 head 之后（见硬约束章节）。

---

## Autocompact 摘要模板（schema 化）

**何时读本节**：当你实现 Level 4 的摘要 prompt 时——自由要点会丢掉"为什么放弃方案 A"，而那恰恰是防止 Agent 重试死路的关键信息。

摘要必须为**结构化 schema**，而非 6 字段自由要点。强制字段如下：

```
CompactSummary {
    goal:                 str   # 用户核心目标（当前任务是什么）
    decisions:            list  # 决策及其理由（按时间序）
    excluded_approaches:  list  # 【必填】已排除的方案及原因——防止重试死路
    plan_status:          str   # 当前计划状态（进行中/受阻/已完成步骤）
    constraints_found:    list  # 发现的约束（环境/接口/权限限制）
    artifacts:            list  # 产出的产物（已改文件、已建对象、引用路径）
    open_tasks:           list  # 未解决/待处理任务
}
```

摘要 prompt 约束：
- `excluded_approaches` 必须逐条给出**方案 + 放弃原因**（如"方案A：直接改全局配置——放弃，因其会破坏多租户隔离"）。
- 文件路径、凭据引用写入 `artifacts` 并同步落外部 scratchpad（见记忆系统），不依赖摘要存活。
- 摘要全文写入 `CompactionLedger.summary_text`，供事后归因。

---

## CompactionLedger（压缩台账）

**何时读本节**：当压缩后 Agent 行为异常、你想归因"它到底丢了什么"时——没有台账，压缩后一犯迷糊无法回溯。

每次压缩（任一级）写入一条 append-only 台账记录。压缩本身是计费的采样步骤（先读完整上下文，单次 ~180K input token），必须可事后复盘。

### 字段骨架

```
class CompactionLedger:
    def record(self, entry: LedgerEntry) -> None:
        raise NotImplementedError(
            "AI: 以 append-only JSONL 写入台账；每次压缩一条；"
            "字段见 LedgerEntry；与 SessionWAL 的 COMPRESSION 事件对齐"
        )

@dataclass
class LedgerEntry:
    seq_id:            str
    level:             int     # 1=Mask 2=Snip 3=Collapse 4=Autocompact
    triggered_at_tokens: int   # 压缩前占用
    freed_tokens:      int     # 释放量
    after_tokens:      int     # 压缩后占用
    cleared:           list[str]  # 被清除/遮蔽的具体内容引用（如 "tool:read_file @msg#42 中段 8000tok"）
    summarized:        list[str]  # 被摘要的跨度（如 "msg#10-#30 折叠为 1 条"）
    summary_text:      str     # Autocompact 摘要全文（Mask/Snip 可为空）
    head_unchanged:    bool    # 断言 head 是否逐字节不变
    timestamp:         str
```

> 台账与 SessionWAL 的 `COMPRESSION` 事件互补：WAL 记"发生了压缩"，台账记"清除了什么、摘要了什么、原文全文"。

---

## 服务端压缩 / Context Editing 对接

**何时读本节**：当你在自建管道与服务端能力之间做架构选择时。

| 方案 | 何时用 | 谁买单 | 备注 |
|------|--------|--------|------|
| 服务端压缩（如 Anthropic Compaction API） | 不想维护客户端记账、上下文可达服务端默认阈值 | 服务端 | 默认累计输入 150,000 token 触发，可配最低 50,000 |
| 自建管道（Mask→Snip→Collapse→Autocompact） | 需要精细控制、低成本优先、自定义台账 | 客户端 | 本章前四节 |
| **两者叠加** | 服务端兜底 + 自建前置遮蔽省成本 | 混合 | **推荐**：自建 Mask/Snip 先省大头，服务端在极端时兜底 |

- **可叠加**：自建 Mask 先把工具输出遮蔽掉（免费、可逆），服务端压缩在更靠后的阈值兜底，两者不冲突。
- **context editing 联动**：服务端 context editing 在清除阈值临近时自动警告模型，让它先把要紧的写进 scratchpad 记忆文件，再清除——与"外部记忆层"安全网天然配合。
- **官方推荐组合**：compaction 保持活跃上下文小且无需客户端记账，memory 保留必须存活于摘要之外的信息。

---

## 硬约束：重建时 head 必须逐字节不变

**何时读本节**：当你实现"上下文重建 / 重注入"逻辑（activeRestore、checkpoint 恢复、跨会话交接）时。

压缩与重建时，**head（system prompt + 任务陈述）必须逐字节不变**。改写 system prompt 会静默摧毁前缀缓存（prefix cache）经济——每次重建都使缓存失效，成本翻倍且延迟上升。

- 任何重建逻辑（activeRestore、checkpoint 恢复、跨会话交接）只能追加/替换 body，不得触碰 head 字节。
- 注入压缩摘要、文件内容、Plan 时，**插入到 head 之后**，而非修改 head。
- 在 `CompactionLedger` 记录 `head_unchanged: bool` 断言，观测可据此报警（见 `references/14-observability.md`）。
- 跨会话的"上下文重置"取舍见 `references/13-long-running-session.md`。
- 压缩成本（LLM 调用、token 消耗）挂到 Budget 见 `references/06-phase-permissions.md`。
- 压缩质量观测（压缩频率、各级占比、`head_unchanged` 断言）见 `references/14-observability.md`。

---

# 记忆系统设计

## 四分类记忆模型

记忆不是模糊的"上下文"，而是有明确生命周期和存储策略的四类数据：

| 类别 | 作用域 | 存储介质 | 生命周期 | 示例 |
|------|--------|----------|----------|------|
| **User** | 用户级别 | 长期存储 | 永不过期 | 用户偏好（语言、代码风格）、常用项目路径 |
| **Feedback** | 项目/任务级 | 长期存储 | 按反馈时效 | "上次你建议用async，但这里用sync更合适" |
| **Project** | 项目级别 | 长期存储 | 随项目演进 | 项目结构、技术栈、依赖关系、约定 |
| **Reference** | 跨项目 | 长期存储 | 按有效期 | API文档摘要、最佳实践片段 |

## 外部记忆层（Scratchpad）

**何时读本节**：当某些信息必须**无损**存活于任意次压缩之外（文件路径、凭据引用、进行中的计划）时。

四分类记忆解决"长期知识沉淀"，但压缩时仍需一个**轻量、可写、外置**的安全网。Scratchpad 是一组简单文本文件，Agent 在压缩前把要紧信息写进去，压缩后再读回来——它**不会**像摘要那样丢信息。

**定位**：压缩的无损安全网。*Notes survive compaction losslessly; summaries do not.*

| 维度 | 四分类记忆 | 外部 Scratchpad |
|------|-----------|-----------------|
| 目的 | 长期知识沉淀 | 跨压缩的临时状态锚 |
| 写入时机 | auto-dream 整合 | 压缩前/关键时刻随手写 |
| 有损性 | 归纳可能丢细节 | 无损（原文文件） |
| 介质 | 长期存储/向量DB | 轻量文本文件 |

### 与压缩的协作

- **Compaction + Memory 是官方推荐组合**：compaction 保持活跃上下文小且无需客户端记账，memory 保留必须存活于摘要之外的信息。
- **context editing 联动**：服务端 context editing 在清除阈值临近时自动警告模型，让它先把要紧的写进 scratchpad 记忆文件，再清除。
- **外置优于内联**：文件路径、凭据引用、运行中的计划写进笔记，可无损存活任意次压缩；摘要做不到。

### memory tool 路径校验安全约束

```
class MemoryTool:
    def write(self, path: str, content: str) -> None:
        raise NotImplementedError(
            "AI: canonicalize(path) 后必须仍在记忆根目录下；"
            "拒绝 ../ 穿越、URL 编码穿越（%2e%2e）、Unicode 等价（NFKC）归一化绕过；"
            "越界一律抛 SecurityError，绝不静默截断到根目录"
        )
```

- `canonicalize` 后用真实绝对路径比对记忆根目录前缀（如 `mem_root/`）。
- 拒绝 `../`、`..%2f`、Unicode 等价字符等所有穿越变体。
- 越界写入抛 `SecurityError`，绝不静默降级到根目录（避免写入逃逸到任意路径）。

### User记忆

存储用户偏好和习惯。结构：
```
UserMemory {
    preferences: { language: "zh-CN", codeStyle: "PEP8", verbosity: "concise" },
    history: [{ query_pattern, preferred_tool, timestamp }, ...]
}
```
User记忆不经过auto-dream——它是累积性的，只在用户显式更新时修改。

### Feedback记忆

存储LLM/Action纠正反馈。结构：
```
FeedbackMemory {
    entries: [{
        correction_type: "tool_choice" | "code_style" | "approach" | "other",
        original_action: String,
        corrected_action: String,
        context_snippet: String,     ← 触发事件前后3轮对话
        timestamp: Timestamp,
        ttl: Duration                 ← 超时自动清理
    }, ...]
}
```
每一行feedback有TTL。例如"代码风格"反馈可能TTL=30天，"tool_choice"反馈可能TTL=7天。

### Project记忆

存储当前项目结构和技术上下文。结构：
```
ProjectMemory {
    root_path: String,
    file_index: Map<Path, FileMeta>,     ← 文件结构快照
    tech_stack: { language, framework, package_manager, ... },
    conventions: [String],                ← 命名规范、目录结构约定
    last_scan: Timestamp
}
```
Project记忆在每次session开始时通过文件系统扫描刷新。刷新策略：比较 `last_scan` 和文件修改时间，仅增量更新。

### Reference记忆

存储外部知识的摘要。结构：
```
ReferenceMemory {
    entries: [{
        source: URL | file_path | "inline",
        topic: String,
        summary: String,              ← 由LLM生成的摘要（≤500 tokens）
        original_length: Int,
        embeddings: Vector,           ← 仅Enterprise
        timestamp: Timestamp
    }, ...]
}
```

---

## Auto-Dream 机制

"Auto-dream"（自动做梦）是将短期记忆整合为长期记忆的异步过程。它的设计灵感来自人类睡眠中的记忆巩固——在Agent空闲或session结束时触发。

### 触发条件（满足任一即触发）

```
条件A: short_term_buffer.length > THRESHOLD_COUNT (默认20)
条件B: session.isEnding == true 且 short_term_buffer.length > 0
条件C: 距离上次auto-dream > DREAM_INTERVAL (默认30分钟) 且 short_term_buffer.length > 5
```

### 做梦流程

```
FUNCTION auto_dream(shortTermBuffer, longTermStore):
    ── 第一步：分类 ──
    classified ← classifyEntries(shortTermBuffer)
    # 返回 {feedback: [...], reference: [...], project: [...], user: [...]}

    ── 第二步：对每类分别整合 ──
    FOR EACH (category, entries) IN classified:
        IF entries IS EMPTY: CONTINUE

        ── 对非Feedback类：调用LLM进行归纳 ──
        IF category ∈ {reference, project, user}:
            dreamPrompt ← 构建类别专属的归纳prompt
            consolidated ← llm.invoke(dreamPrompt + 序列化(entries))
            longTermStore.upsert(category, consolidated)

        ── 对Feedback类：逐条持久化（不归纳，保留精确内容）──
        ELSE IF category == "feedback":
            FOR EACH entry IN entries:
                longTermStore.appendFeedback(entry)

    ── 第三步：清空短期缓冲 ──
    shortTermBuffer.clear()

    ── 第四步：记录dream日志 ──
    SessionWAL.write({
        type: "AUTO_DREAM",
        entries_count: totalEntries,
        categories: classified.keys()
    })
```

### 归纳Prompt模板（按类别）

```
用于 Reference 记忆：
"请将以下多条相关reference条目归纳为一条不超过500 tokens的摘要。
 保留所有可复用的代码模式、API签名和关键数值。"

用于 Project 记忆：
"请将以下项目结构变化记录合并到现有Project记忆中。
 仅更新有变化的部分，不变的部分不重复。"

用于 User 记忆：
"请提取以下用户交互中的新偏好或习惯变更。
 仅输出变更项，已存在的偏好不重复。"
```

---

# Session WAL 设计集成

Session WAL（Write-Ahead Log）是会话的持久化事件日志，采用追加写入的JSONL格式，是恢复和审计的基础设施。

## 设计原理

- **追加仅写**：每行一个JSON事件，尾部追加，O(1)写入
- **幂等可回放**：每个事件有唯一 `seq_id`，重放时跳过已处理的序列号
- **崩溃安全**：每个事件写入后 fsync，保证磁盘持久化
- **定时checkpoint**：每N个事件后创建快照行，减少重放启动时间

## 5种事件类型

| 类型 | 字段 | 含义 |
|------|------|------|
| `USER_INPUT` | `{seq_id, content, timestamp}` | 用户发送消息 |
| `TOOL_CALL` | `{seq_id, tool_name, params_hash, timestamp}` | Agent调用工具（不记录完整参数，仅hash） |
| `TOOL_RESULT` | `{seq_id, tool_name, result_tokens, success, error?, duration_ms, timestamp}` | 工具执行结果摘要 |
| `COMPRESSION` | `{seq_id, level, input_tokens, output_tokens, duration_ms, timestamp}` | 压缩事件 |
| `CHECKPOINT` | `{seq_id, messages_tokens, memory_size, pending_tasks[], timestamp}` | 会话快照 |

### 事件格式示例

```jsonl
{"seq":1,"type":"USER_INPUT","content_hash":"a1b2c3","timestamp":"2026-05-20T10:00:00Z"}
{"seq":2,"type":"TOOL_CALL","tool":"read_file","params_hash":"d4e5f6","timestamp":"2026-05-20T10:00:01Z"}
{"seq":3,"type":"TOOL_RESULT","tool":"read_file","result_tokens":1200,"success":true,"duration_ms":45,"timestamp":"2026-05-20T10:00:01Z"}
{"seq":4,"type":"CHECKPOINT","messages_tokens":45200,"memory_size":12,"pending_tasks":["fix_bug_1"],"timestamp":"2026-05-20T10:05:00Z"}
{"seq":5,"type":"COMPRESSION","level":1,"input_tokens":98000,"output_tokens":65000,"duration_ms":2,"timestamp":"2026-05-20T10:10:00Z"}
```

## 重放/恢复机制

```
FUNCTION replay_session(walFile):
    lastCheckpoint ← NULL
    eventsAfterCheckpoint ← []

    ── 第一遍扫描：找最近checkpoint ──
    FOR EACH line IN walFile (逆序):
        event ← parseJSON(line)
        IF event.type == "CHECKPOINT":
            lastCheckpoint ← event
            BREAK

    ── 第二遍扫描：从checkpoint之后重放 ──
    startSeq ← lastCheckpoint?.seq ?? 0
    FOR EACH line IN walFile WHERE line.seq > startSeq:
        event ← parseJSON(line)
        eventsAfterCheckpoint.append(event)

    ── 重建会话状态 ──
    sessionState ← {
        pendingTasks: lastCheckpoint.pending_tasks,
        messagesTokens: lastCheckpoint.messages_tokens,
        replayEvents: eventsAfterCheckpoint
    }
    RETURN sessionState
```

**恢复场景**：
- **进程崩溃**：重启时从WAL恢复会话状态，重放未完成的事件
- **网络中断**：API调用中断时，从WAL确定最后成功步骤，避免重复操作
- **手动回滚**：定位到特定 seq_id 的checkpoint，将对话状态回滚到该点

---

# AI构建提示

以下是面向AI编码助手的实现指引，不是面向用户的文档。

```
BUILD INSTRUCTIONS FOR AI:

1. 首先实现 tokenCounter 模块 —— 它是所有压缩算法的基础。
   使用 tiktoken（对应模型的编码器），不要用 len/4 估算。
   tokenCounter 必须提供：
   - count(text: str) → int
   - countMessages(messages: list) → int
   - countStructured(msg: dict) → int  （含 role 和 tool_calls 的 overhead）

2. 压缩管道按 **Mask→Snip→Collapse→Autocompact** 的顺序实现（Mask 必为首）。
   每个 Level 是一个独立类，实现统一的 compress(request)→Optional[CompressionResult] 接口。
   不要在 CompressionPipeline.compact() 中写 if-else 分发——使用策略链模式，
   链式尝试直到第一个非 None：先 Mask，不足再 Snip，再 Collapse，最后 Autocompact。
   Autocompact 摘要必须用 schema 模板（含 excluded_approaches），并写入 CompactionLedger。

3. MemoryManager 必须是异步安全的。
   短期缓冲区用 asyncio.Lock 保护，长期存储用文件锁或DB事务。
   auto-dream 必须在后台线程/协程中执行，不得阻塞主Agent循环。

4. SessionWAL 写入路径必须使用 append-only 文件打开模式（'a'）。
   每个事件写入后调用 flush()（非 fsync，仅在checkpoint时 fsync）。
   WAL文件按 session_id 命名：wal_{session_id}.jsonl

5. 恢复机制的关键：compaction 后必须立即在 WAL 中写 CHECKPOINT 事件，
   记录当前压缩级别、剩余 token 数、待处理任务列表；同时写一条 CompactionLedger 台账。
   这使得崩溃恢复时可以知道"压缩到了哪一步"以及"清除了/摘要了什么"。

6. 不要在压缩后丢弃文件内容引用 —— 维护一个 currentFiles[] 列表，
   每次 compaction 后将文件内容、Skill 上下文、Plan、任务列表**注入到 head 之后**，
   **不得改写 head（system prompt + 任务陈述）**，以保住前缀缓存经济。

7. hasAttemptedReactiveCompact 标志：
   - 初始化为 false
   - 任何一次 compaction 调用后设为 true
   - 仅在成功处理LLM响应后重置为 false
   - 如果 compaction 后立刻再次触发 compact（错误恢复循环），
     检测到 flag=true 时跳过压缩，返回错误让上层决定降级或放弃
```

---

# 规模适应性指南

## Minimal 配置

适用于：原型开发、个人项目、单次短对话。
- 压缩：仅 Level 1 Mask（工具结果遮蔽）。Snip 阈值设为 50 条消息，一般不触发。
- 记忆：不使用四分类；可选轻量 scratchpad 备忘。
- WAL：不使用。崩溃后对话无法恢复。
- Token计数：允许 `len/4` 估算。

```
示例场景：写一个200行的Python脚本，对话不超过30轮。
Mask 偶尔遮蔽超长 read_file 输出，其余上下文完全足够。
```

## Professional 配置

适用于：日常开发、中等复杂度项目、多文件编辑。
- 压缩：完整四级管道 **Mask→Snip→Collapse→Autocompact**，触发阈值 0.65；Mask 按工具 `outputProfile`（read_file≈8000、bash≈2000），Snip 阈值=20 条，Collapse 窗口=15 条。
- 记忆：文件级。四分类 + scratchpad 存储为独立 JSON 文件，auto-dream 仅触发条件 B（session 结束）。
- WAL：JSONL 文件，每 100 事件 checkpoint 一次；压缩同时写 CompactionLedger。
- Token计数：使用 tiktoken 精确计数。

```
示例场景：跨5个文件的bug修复，对话100+轮。
Mask 先清掉工具输出大头，Snip/Collapse 覆盖剩余，仅在极端情况触发 Autocompact。
```

## Enterprise 配置

适用于：持续运行Agent、大型项目、多session协作。
- 压缩：四级 + 压缩恢复（compaction 后自动重建被压缩的上下文）+ **外部 scratchpad 安全网** + **服务端压缩叠加**（自建前置遮蔽省成本，服务端极端兜底）。
- 记忆：向量数据库（如Qdrant/Chroma）。四分类各建一个 collection；scratchpad 落独立文件区。
  - User记忆索引在 `user_preferences` collection
  - Project记忆增量更新，每次文件变更自动更新 embeddings
  - auto-dream 全量触发（条件 A+B+C），在后台协程中执行，不阻塞主循环
- WAL：JSONL + SQLite 双写；CompactionLedger 独立 append-only 文件。
- Token计数：模型原生 tokenizer + 预留 1000 token buffer。
- 附加值：压缩事件可观测（metrics 上报压缩频率、各级占比、节省 token 数、`head_unchanged` 断言命中率）。

```
示例场景：持续运行数月的CI/CD Agent。
Enterprise 配置确保跨 session 记忆连续，scratchpad 让要紧信息无损存活任意次压缩。
```

---

# 检查清单

- [ ] tokenCounter使用模型原生tokenizer，非估算
- [ ] 压缩触发阈值 60-70%（默认 0.65），非 85%
- [ ] **Mask 为管道首选**：先于 Snip 执行，按工具 `outputProfile` 差异化阈值
- [ ] Mask 标记 `masked: true` 防止重复遮蔽，原消息保留仅生成遮蔽视图
- [ ] Snip 后注入 system 消息声明"已剪断"
- [ ] Context-Collapse 不修改原 messages 数组，仅读时投射
- [ ] Collapse 去重检查（bloom filter）
- [ ] Autocompact 从尾向头扫描，保留最近 10 条消息
- [ ] **Autocompact 摘要为 schema 化模板，必含 `excluded_approaches`（已排除的方案及原因）**
- [ ] 每次压缩写入 CompactionLedger（before/after token、cleared、summarized、summary_text 全文）
- [ ] 压缩后恢复：文件内容、Skill上下文、Plan、任务列表
- [ ] **重建上下文时 head（system prompt + 任务陈述）逐字节不变**，`head_unchanged` 断言置 true
- [ ] 外部 scratchpad 与四分类记忆分工明确（无损安全网 vs 长期知识）
- [ ] memory tool 路径校验：canonicalize 后仍在记忆根目录，拒绝 `../` 与编码穿越
- [ ] 服务端压缩/context editing 与自建管道可叠加（可选）
- [ ] hasAttemptedReactiveCompact标志正确维护
- [ ] 压缩后写入WAL CHECKPOINT事件
- [ ] 记忆四分类各独立存储，auto-dream对各类用不同策略
- [ ] auto-dream异步执行，不阻塞Agent主循环
- [ ] WAL追加写入，每行JSON独立
- [ ] WAL恢复机制可处理崩溃/中断/手动回滚

---

# 常见陷阱

## 陷阱1：压缩后丢失关键状态

**症状**：Agent在压缩后突然"失忆"——忘记正在编辑的文件、忘记当前Plan的第几步、忘记已加载的Skill指令。

**根因**：压缩算法只处理了消息历史，但没有主动重建易失上下文。

**解决（必须实现）**：
- 每轮压缩完成后，执行 `activeRestore` 步骤：
  1. 检查 `currentFiles[]` 列表，对每个当前工作文件调用 `read_file` 并将结果注入为 system 消息
  2. 检查 `activeSkill`，将 Skill 的核心指令（前1500 tokens）重新注入 system prompt
  3. 检查 `activePlan`，将计划摘要（当前步骤+下一步）注入 system prompt
  4. 检查 `pendingTasks[]`，将待处理任务列表注入 system prompt
- `activeRestore` 是压缩管道的强制后置步骤，不是可选优化。

## 陷阱2：无限压缩循环

**症状**：compaction → 释放空间 → LLM生成大量输出 → 再次触发compaction → 释放空间 → ... 死循环。

**根因**：压缩后上下文仍然不足，或压缩释放的空间被新响应立即填满。

**解决（必须实现）**：
- `hasAttemptedReactiveCompact` 标志：
  - 初始值 `false`
  - compaction() 调用时设为 `true`
  - 仅在成功接收并处理完一次完整的LLM响应后重置为 `false`
  - 如果 `true` 时再次检测到需要压缩：**跳过压缩**，返回 `CONTEXT_EXHAUSTED` 错误
- 上层捕获 `CONTEXT_EXHAUSTED` 后执行降级策略：
  - **Professional**：仅保留最后3条消息+system prompt，强制Level 4压缩
  - **Enterprise**：触发全量Autocompact+clear所有非关键记忆

## 陷阱3：Token计数不精确

**症状**：明明预算还有空间，API却报 `context_length_exceeded`。或者：明明还可以发更多消息，却过早触发压缩。

**根因**：使用 `len(content)/4` 估算，忽视 tool_calls、role 标注、system prompt 等元数据的token开销。

**解决**：
- 必须使用模型原生tokenizer（tiktoken或HuggingFace tokenizer匹配模型）
- 每条消息的token计数必须包含：`role` 字段的markers（~4 tokens）+ 内容本身的tokens + `tool_calls` 结构的JSON overhead
- 预留5%安全buffer：`effectiveBudget = maxTokens * 0.95`
- 在 budget 的 60-70% 处触发压缩（而非 85% 或 100%）：为压缩过程本身预留操作空间，且避开 50K token 起的 context rot 退化区，保证 Autocompact 在模型尚可推理时完成

## 陷阱4：auto-dream阻塞主循环

**症状**：session结束时Agent卡死数秒。

**根因**：auto-dream中调用了LLM进行归纳，而归纳请求阻塞了主循环退出。

**解决**：
- auto-dream必须在独立的后台协程/线程中执行
- session结束时的auto-dream使用 `timeout`（例如5秒），超时则直接写原始条目（不归纳）
- 不要等待auto-dream完成才返回结果给用户

## 陷阱5：WAL文件无限增长

**症状**：长时间运行后 WAL 文件达到数GB。

**解决**：
- 每次CHECKPOINT后，标记该checkpoint之前的所有事件为"可归档"
- 每N个checkpoint后（例如10个），将旧事件归档到 `wal_archive/`，删除主WAL中已归档行
- archive保留7天，过期自动清理

---

## 下一步

完成Phase 5后，进入 **Phase 6: 权限安全**（参考 `references/06-phase-permissions.md`）

---

# 双层循环上下文隔离 (v4)

> 配合 Phase 4 的 Loop Engineering 升级，引入 Outer Loop（规划层）与 Inner Loop（执行层）的上下文分离策略，避免中间工具输出污染战略决策。

## 设计原理

双层循环架构的核心挑战不是"如何执行"，而是**如何防止 Inner Loop 的噪音污染 Outer Loop 的决策质量**。

这本质上是 ReWOO（Reasoning WithOut Observation）的核心洞察：观测数据（工具输出）不应混入推理过程——它会把推理链污染成"我看到 X，所以做 X"，而非"基于目标，我需要 X"。

## 上下文分离策略

```
┌─────────────────────────────────────────────────────┐
│               Outer Loop (Planner)                   │
│  上下文: 任务描述 + 已完成步骤摘要 + 当前步骤        │
│  ❌ 不包含: 原始工具输出、中间文件内容                │
│  ✅ 包含: 执行结果结构化摘要（成功/失败/关键发现）    │
├─────────────────────────────────────────────────────┤
│               Inner Loop (Executor)                  │
│  上下文: 当前步骤描述 + 前一步结果摘要 + 工具输出     │
│  ✅ 包含: 原始工具输出（仅为当前步骤执行用）         │
│  ❌ 不包含: 全局任务、其他步骤的细节                  │
└─────────────────────────────────────────────────────┘
```

## 正确做法 vs 错误做法

### ❌ 错误：Inner Loop 输出全部回传给 Outer Loop

```python
# 错误：将 Inner Loop 的原始工具输出直接传给 Outer Loop
async def outer_loop(self, task: str):
    for step in self.plan.steps:
        result = await self.inner_loop(step)
        # ❌ 把 Inner Loop 的全部消息历史直接追加到 Outer Loop 上下文
        self.context.extend(result["messages"])  # 污染！
        self.context.append({
            "role": "user",
            "content": result["output"],  # 包含大量原始工具输出
        })
```

### ✅ 正确：Inner Loop 只返回结构化摘要

```python
# 正确：Inner Loop 返回结构化摘要，Outer Loop 只接收关键信息
@dataclass
class StepSummary:
    """Inner Loop 执行结果的结构化摘要"""
    step_id: str
    success: bool
    key_findings: str        # 关键发现（1-2 句话，不含原始输出）
    files_modified: List[str] # 修改的文件列表
    errors: List[str]         # 错误信息（如有）
    next_hint: str            # 给下一步的提示（如有）

async def outer_loop(self, task: str):
    for step in self.plan.steps:
        summary = await self.inner_loop(step)
        # ✅ 只将结构化摘要注入 Outer Loop 上下文
        self.context.append({
            "step": step.id,
            "summary": summary.key_findings,
            "status": "success" if summary.success else "failed",
        })
        if not summary.success:
            await self._replan(step, summary.errors)
```

## 上下文污染陷阱

将 Inner Loop 的原始工具输出直接传给 Outer Loop 会导致以下问题：

1. **决策质量下降**：Outer Loop 的 Planner 看到大量工具输出后，会倾向于"基于看到的内容做决策"，而非"基于目标做决策"
2. **Token 浪费**：原始工具输出（如文件内容、命令输出）可能包含大量冗余信息，占用 Outer Loop 有限的上下文窗口
3. **计划偏离**：Planner 被工具输出中的细节吸引，失去全局视野，频繁修改计划导致任务漂移

## 规模适配

- **Minimal**：不使用双层循环，无需上下文隔离。
- **Professional**：固定计划执行，Inner Loop 返回简单的成功/失败 + 错误信息。
- **Enterprise**：完整上下文隔离，Inner Loop 返回 StepSummary 结构化摘要，Outer Loop 仅接收摘要。

## AI 构建提示

```
根据用户选择的规模实现双层循环上下文隔离：

Professional 级别：
  1. Inner Loop 执行完成后返回 {success: bool, error: str, output: str}
  2. Outer Loop 只记录 success 和 error，不记录完整 output
  3. 如果步骤失败，Outer Loop 将 error 注入为"重新规划"的上下文

Enterprise 级别：
  1. 实现 StepSummary dataclass，包含 key_findings / files_modified / errors / next_hint
  2. Inner Loop 末尾调用 LLM 生成结构化摘要（不追加到 Inner Loop 上下文）
  3. Outer Loop 只接收 StepSummary 对象，不访问 Inner Loop 的消息历史
  4. 动态重规划时，Planner 只看到 StepSummary 列表，不看到原始工具输出

关键约束：
  □ Inner Loop 的原始消息历史绝不传递给 Outer Loop
  □ 摘要生成使用低成本模型（如 gpt-4o-mini），不增加 Planner 的 Token 消耗
  □ 摘要必须在 Inner Loop 的独立上下文中生成，不污染 Planner 的上下文
  □ 如果 Inner Loop 超过 5 次尝试仍然失败，摘要中必须明确标记"需要人工介入"
```