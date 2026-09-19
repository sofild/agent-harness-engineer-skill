# Phase 3: 工具系统

> 版本 v4。本文件对应 **优化点 B2：工具系统反转**——从"多而全"彻底转向"**少而精 + 代码执行**"。

---

## 何时读本节

- 你正在设计或裁剪 Agent 的工具集（"该给 Agent 几个工具？哪些是强工具？"）。
- 你发现 Agent **选错工具、漏填参数、重复调用**——准确率低，但直觉是"再加几个工具"。
- 你面临 **上下文被工具定义/结果撑爆**，想在不破坏 prompt cache 的前提下扩展工具。
- 你的任务包含 **多步线性数据处理**（10+ 次读文件、批量转换、聚合），想用代码执行替代 N 次工具调用。
- 你对接 MCP 外部工具生态（见 `references/10-mcp-integration.md`）或在沙箱中跑代码（见 `references/12-sandbox-advanced.md`）。

---

## 目标

Phase 3 负责 Agent 的"手"——工具注册、调度、安全与结果处理。v4 的核心反转：**工具数量不是越多越好**。

三个月前的旧认知（工具数量 3-5 / 10-20 / 50+，按 Claude Code 的 43+ 工具五类体系 `agent / workflow / task / plan / advanced` 组织，延迟加载仅静态分类 + 关键词匹配）**与 2026 的共识正好相反**。新版主张三条主线：

1. **少而精**：先给最小可用集，靠"少"控制准确率，靠"减"而非"加"调优。
2. **代码执行**：用一次沙箱脚本执行替代十次工具调用，把上下文压力变成编程问题。
3. **tool search**：在不破坏 prompt cache 的前提下，让工具目录可以任意大。

---

## 设计哲学联动

`references/08-core-concepts.md` 的"十大设计哲学"已新增 **第 11 条：工具少而精，代码执行优于多次工具调用**。本节是第 11 条哲学的落地实现。阅读本节时，请把它与第 7 条"上下文即稀缺资源"、第 4 条"缓存前缀稳定性"对照理解——少而精与代码执行最终服务的都是同一个目标：**让上下文里只出现 Agent 此刻真正需要的信息**。

---

## 设计原理

### 1. 工具即 Prompt（且是写给 Agent 的，不是人类的）

工具描述（Description）本质上是**写给 LLM 看的 Prompt**——而且它是写给"一个会调用工具的 Agent"的，不是写给人读 API 文档的。这是 v4 反转的第一块基石：**工具是为 Agent 设计的，不能从人类 API 直接搬运**。

描述越详细、越贴合 Agent 的调用心智，LLM 调用参数越准确。每个工具的 `description` 应当包含：

- **功能说明**：工具做什么，一句话概括
- **适用场景**：什么情况下应该选用此工具（而非另一个相似工具）
- **使用时机与反例**：不仅说"何时用"，还要说"**何时不用 / 常见误用**"（这是"为 Agent 设计"的硬性要求）
- **参数语义**：每个参数的含义、格式、约束、默认值
- **返回结果说明**：返回值的数据结构和含义
- **错误信息即纠正提示**：失败时 `error` 字段不是堆栈，而是可让 LLM 自我纠正的自然语言（详见原则 ②）

Schema 验证是把第二道关——即便描述不够好，Schema 也能在运行时拦截参数类型错误。但描述好 + Schema 严才是最佳实践。

> ⚠️ 反模式：直接把 REST API 的 OpenAPI schema 翻译成工具描述。人类 API 强调"细粒度、正交、可组合"，Agent 需要的是"强有力、边界清晰、带时机与反例"。**细粒度正交 API 往往是工具合并的候选，而非工具数量膨胀的来源。**

### 2. 工具设计三原则（v4 新增，全文核心）

这是 Phase 3 的方法论总纲。三条原则相互支撑：**少而精**给出数量纪律，**为 Agent 设计**给出质量纪律，**反比关系**给出底层理由。

#### 原则 ①：少而精

**数量上限建议（常驻给 LLM 的工具，非工具目录）**

| 规模 | 常驻强工具数量上限 | 说明 |
|------|------------------|------|
| Minimal | 1-3 个 | 一个文件 IO + 一个代码执行，往往就够了 |
| Professional | 5-8 个 | 超过 8 个必须论证不可替代性 |
| Enterprise | 个位数常驻 + 大目录 | 目录可含几十~几百，但靠 tool search 暴露，常驻 LLM 的仍是个位数 |

**工具合并判据**：当候选工具满足以下**任一**条件，应合并为单一工具（用参数区分模式）：

- **对象同一 + 参数正交**：`read_file` / `write_file` → `file_io(mode="read"|"write")`
- **必然前后置且不可独立使用**：A 的输出恒为 B 的输入，单独调哪一个都没意义
- **同一能力的不同"模式"**：`search_by_keyword` / `search_by_semantic` → `search(strategy="keyword"|"semantic")`
- **合并后描述增量可控**：描述变长但 LLM 仍能准确选择，且参数数量仍 ≤ 7 个必填

**不合并的反向判据**（避免"巨无霸工具"）：

- 合并后职责模糊，LLM 需要在调用前做复杂分支判断才能选对 mode
- 参数爆炸（必填 > 7 个，或互斥参数组相互牵制）
- 两个操作的失败模式、权限等级、安全边界差异巨大（如"读"与"删"绝不能合并）

```
合并决策伪代码（抽象，非可执行）：
  function should_merge(tool_a, tool_b):
    if same_target(tool_a, tool_b) and orthogonal_params(tool_a, tool_b):
      return MERGE                       // 对象同一、参数正交
    if is_strict_predecessor(tool_a, tool_b):
      return MERGE                       // 必然前后置
    if same_capability_diff_mode(tool_a, tool_b):
      return MERGE                       // 同一能力不同模式
    if merged_required_params(tool_a, tool_b) > 7:
      return KEEP_SEPARATE               // 参数爆炸，不合并
    if distinct_security_boundary(tool_a, tool_b):
      return KEEP_SEPARATE               // 安全边界不同，不合并
    return REVIEW                        // 人工裁决
```

**"先减后加"调优路径（唯一推荐的扩工具路径）**：

```
1. 起步：只给最小可用集（Minimal 1-3 个强工具）。
2. 观察：跑真实任务，记录哪类任务反复失败 / 需要 Agent 多次重试。
3. 判断：该失败是否因为"缺工具"？多数时候是描述不清、或可用代码执行编排，
         而非真缺一个工具。
4. 加工具（仅当）：某类任务反复失败，且无法用现有工具合并或代码执行替代时，
         才加第 N+1 个，并论证不可替代性。
5. 定期审计：调用频率 < 5% 会话使用的工具，考虑移除或合并回既有工具。
```

核心论断（经验支撑）：**少数强大工具 >> 大量狭窄工具**。与其堆 15 个窄工具，不如打磨 2 个强工具。

#### 原则 ②：为 Agent 设计

工具不是给人类用的函数，是给 LLM 决策调用的"接口"。三个硬性设计要求：

**a) 描述必须含"使用时机"与"反例"。** 光说"做什么"不够，必须说"**何时用、何时不用**"。LLM 在工具之间选错，90% 是因为描述没划清边界。

```
好描述片段（抽象示范）：
  search(strategy): 在代码库中检索。
    用：需要按内容/语义定位文件或符号时。
    不用：要读取已知路径文件的完整内容时——请用 file_io(mode="read")，
          search 只返回位置，不返回全文。   ← 这条反例直接防住误用
```

**b) 错误信息即纠正提示（强制性要求）。** 工具执行失败时，`ToolResult.error` 字段**绝不能**是原始堆栈或 `"Error: 500"`。它必须是一句**能让 LLM 下一轮自我纠正**的自然语言提示，指出"你哪里传错了、正确做法是什么"。

```
错误示范（禁止）：error = "ValueError: invalid path"
纠正示范（要求）：error = "参数 path 必须是相对 workdir 的路径，你传入了绝对路径
                      '/root/x'。请改为相对路径如 'src/x'，或先用 list_dir 确认结构。"
```

> AI 构建提示：错误处理层应把异常**转写为纠正性提示**，而不是透传。这是"工具为 Agent 设计"最容易被忽略、却对准确率影响最大的一环。

**c) 返回结构化且精简。** 工具只回传 Agent 后续推理**真正需要**的最小字段集。大对象分页、长列表截断、无关字段投影掉。记住：每个回传 token 都占上下文预算（第 7 条哲学）。

#### 原则 ③：工具数量与准确率的反比关系

**核心论断**：在"职责清晰、描述充分"的前提下，工具数量与 Agent 调用准确率呈**反比**。这不是经验主义，有可量化证据：

- **Vercel 实证**：把 Agent 工具从 **15 个砍到 2 个**，任务准确率从 **80% 飙升到 100%**。
- **机制解释**：
  - 工具越多，LLM 在"选哪个"上的决策面越大，误选概率上升；
  - 描述总量挤占上下文与注意力预算，单工具描述质量被稀释；
  - 工具间边界模糊，相似工具互相"抢调用"，导致参数错位。
- **但注意平衡**：反比关系有前提——单个工具职责**不能过度膨胀**（参数爆炸会反噬准确率）。真正的最优解是"**少且强**"，而不是"少且废"。

```
准确率 vs 工具数量（定性曲线，非实测数据）：
准确率
 100% |        ● (Vercel: 2 工具)
      |      ╱
  80% |   ● (Vercel: 15 工具)
      |  ╱
      | ╱
      |╱___________________ 工具数量 →
  拐点：超过"强工具上限"（Pro 8 个 / Ent 个位数常驻）后准确率持续下滑
```

### 3. 工具分区算法（Tool Partitioning）

只读工具可并发执行，写入工具需串行化（与 v3 一致，保留）：

```
分区原则：
  只读（Read）  = 文件读取搜索、网络GET请求、只读DB查询    → 可并发
  副作用（Write）= 文件写入/删除、Shell执行、POST/PUT/DELETE → 串行队列

算法伪代码：
  function partition(tool_calls):
    reads = [t for t in tool_calls if t.is_concurrency_safe]
    writes = [t for t in tool_calls if not t.is_concurrency_safe]
    results = {}
    for each batch in chunk(reads, max_concurrent=5):
      results += parallel_execute(batch)
    for tool in writes:
      results += execute(tool)
    return results
```

**为什么需要分区**：上下文窗口资源有限，若 LLM 一次返回 10 个 tool_call，其中 3 个写文件 + 7 个读文件，先并发跑完 7 个读操作能提前释放网络/IO 等待，再串行处理 3 个写操作避免数据竞争。

> 注：当多步只读操作可预测时，优先考虑用 **CodeExecution（见 §5）** 一次性编排，而非发 10 个独立 tool_call——后者既占分区调度，又灌入 10 份结果。

### 4. 工具依赖声明

某些工具之间存在前置依赖——工具 A 的输出是工具 B 的输入：

```
依赖声明接口：
  interface ToolDependency:
    tool_name: string          // 当前工具名
    depends_on: string[]       // 依赖的工具名称列表
    resolver: function         // 如何从依赖结果中提取参数

示例：
  Tool("generate_report") depends_on ["user_query_analysis", "data_fetch"]
  → 先执行 user_query_analysis 和 data_fetch，取其结果传给 generate_report
```

执行调度时，依赖图决定调用顺序：无依赖的工具可并发，有依赖的需等待上游完成。

### 5. CodeExecution 工具模式（v4 新增）

**核心思想（Anthropic）**：与其让 Agent 发 N 个工具调用，不如让 Agent **写一个脚本编排整个工作流**，脚本在**沙箱**里一次性跑完，**只有最终输出进入上下文**。这就是"**think in code**"范式：把十次文件读取换成一次脚本执行，把上下文压力变成**编程问题而不是压缩问题**（压缩是 LLM 的弱项，编程是 LLM 的强项）。

```
CodeExecution 工作流（抽象）：
  Agent ──write_script──> script（编排多步调用/计算）
        ──sandbox_run──> 沙箱执行：
              ├─ 无网络（或最小白名单）
              ├─ 最小权限（workdir 内）
              ├─ CPU / 内存 / 时间 限额
              └─ 输出扫描（注入模式检测，防 prompt injection）
        ──returns──> 只回传最终结构化结果（不回传中间步骤）
```

**Token 收益（量化对比）**：

| 方式 | 工具定义 | 调用 | 结果 | 合计 |
|------|---------|------|------|------|
| 传统 10 次调用 | 10K | 5K | 35K | **50K token** |
| CodeExecution 1 次 | 200 | 2K | 1K | **3.2K token** |

→ **降 98.7%**。收益随步骤数线性放大。

**抽象接口骨架（仅契约，不可执行）**：

```
interface CodeExecutionTool:
    name: string                        // 如 "code_exec"
    description: string                 // 须含：编排多步任务时用；不适合 1-3 步
    sandbox_policy: SandboxPolicy       // 无网络/最小权限/资源限额（见 references/12-sandbox-advanced.md）
    execute(script: str, lang: str) -> ToolResult:
        raise NotImplementedError("AI: 在沙箱中执行 script；
            仅回传最终输出；中途步骤不得进入上下文；
            执行前做输出扫描检测注入模式；超时/超限返回纠正性 error")
```

> AI 构建提示：实现时把"是否命中沙箱资源限额、是否检测到注入模式"都转写为**纠正性 error**（见原则 ②b）。

#### 适用边界（明确）

适合用 CodeExecution：

- **多步线性/循环数据处理**：10+ 次文件读取、批量格式转换、跨文件聚合计算。
- **本地计算优于 LLM 推理**：排序、统计、正则提取、数据清洗——这些 LLM 不擅长，代码擅长。
- **结果可收敛为单一输出**：管线末端能归纳为一个结构化结果或摘要。
- **检索即工具（A-RAG）场景**：检索不预先灌进上下文，而是暴露 `关键词搜索 / 语义搜索 / chunk 读取` 三个检索工具，让 Agent 按推理需要**增量拉取**——脚本可编排这三次检索并只回传命中 chunk。

#### 不适用边界（明确，必须写清）

**以下情况不要用 CodeExecution，退回普通多步工具调用**：

1. **1-3 步的任务不用**：代码执行有固定的脚本编写 + 沙箱启动开销，短任务直接调用更高效。
2. **交互式 / 需要人类中途反馈的不用**：脚本是一次性批处理，无法在中间 `await` 人类确认或中途改方向。
3. **需要依据中间结果动态选工具的不用**：Agent 才能"看一步走一步"做推理分支；脚本无法在运行中"思考"下一步该调哪个工具。
4. **有不可逆副作用且需人类确认的操作不用**：写数据库、部署、发消息——这些应由带权限门禁（见 `references/08-core-concepts.md` 权限模型）的显式工具执行，而非藏在脚本里绕过审批。
5. **无法收敛为单一输出的探索性任务不用**：若中间产物本身就要进上下文给 Agent 看，代码执行省不了 token。

```
决策判据（抽象）：
  if steps <= 3:                          → 普通工具调用
  if needs_human_midway:                  → 普通工具调用（带 ask_user）
  if branch_depends_on_intermediate:      → 普通工具调用（Agent 推理）
  if has_irreversible_side_effect:        → 显式权限工具（非脚本）
  if steps > 3 and convergent and safe:   → CodeExecution  ✅
```

### 6. 工具延迟加载 → tool search（v4 升级）

旧方案（静态分类 + 关键词匹配）的两个死穴：**(1)** 预筛选仍要把被选中的完整定义塞进消息前缀，**破坏 prompt cache**；**(2)** 关键词匹配粗暴，常漏掉语义相关工具。v4 升级为 **tool search**。

**tool search 是什么**：工具定义不全量发给 LLM。LLM 先看到一份**轻量目录**（每个工具仅名称 + 一句话摘要），当推理需要某个能力时，调用一个 `tool_search` 工具，按语义**动态发现**并**按需加载该工具的完整定义**（作为工具结果返回，而非消息前缀）。

```
tool search 流程（抽象）：
  LLM 视野 = [轻量目录: name + one_line_summary] × N
       │
       ├─ 需要某能力 → 调 tool_search("批量重命名 python 文件")
       │       → 返回匹配工具的完整 definition（含 description/schema）
       │       → LLM 据此发起真实调用
       └─ 不相关工具的定义永远不进上下文
```

**为何对 prompt cache 零影响（关键论证）**：

- tool search 已是 **GA（正式可用）** 状态。
- 每个工具定义加一个 boolean 标记（如 `lazy: true`），标明"不进稳定前缀，仅按需经 search 返回"。
- 完整定义**不出现在 system_prompt 工具区**，因此**不动缓存前缀**（第 4 条哲学：内置工具排序作稳定前缀）。被 search 拉取的定义是**工具结果**，走的是消息区而非前缀区。
- **工具目录越大，收益越高**：目录从 20 涨到 200，常驻前缀几乎不增长（只涨轻量目录那几十字摘要），而旧方案要么全发（前缀爆炸）、要么关键词预筛（前缀随筛选集波动而失稳）。tool search 是**唯一对 prompt cache 零代价的杠杆**。

```
缓存前缀对比：
  旧（全发/预筛）：[system][tools 10K...变动...] → 前缀失稳，缓存命中率↓  ✗
  新（tool search）：[system][轻量目录 ~0.5K 稳定] + [messages 含 search 结果] → 前缀稳定 ✅
```

> 与 MCP 的联动：外部 MCP 工具天然适合走 tool search 暴露（见 `references/10-mcp-integration.md`）。MCP 工具本就动态发现，不必常驻前缀。

### 7. 工具输出后处理钩子（v4 前移）

原"结果截断"策略**前移**为**工具输出后处理钩子（post-processing hook）**：在工具结果**进入上下文之前**就压缩，而不是事后靠四级压缩管道兜底（见 `references/08-core-concepts.md` 上下文压缩）。

```
后处理钩子链（抽象，进入上下文前依次执行）：
  raw_result
    → truncate       // 超长则头尾保留 + 中部摘要
    → project        // schema 投影：只留 Agent 后续需要的字段
    → dedup          // 去重重复行/块
    → scan           // 注入模式扫描（与 CodeExecution 共用扫描器）
    → into_context   // 此时才写入 Session（见 references/13-long-running-session.md）
```

**原则**：压缩发生在"边界处"而非"事后"。上下文预算（第 7 条哲学）最贵的环节是"已经进上下文再压缩"，前移能省下这部分浪费。

### 8. MCP 工具适配器

MCP（Model Context Protocol）定义了工具发现和调用的标准协议（完整协议与六种传输见 `references/10-mcp-integration.md`）。项目需提供适配层将外部 MCP Server 的工具映射为内部 Tool 接口：

```
MCP适配器抽象：
  interface MCPAdapter:
    connect(server_config)        → 建立与 MCP Server 的连接
    list_tools()                  → 获取 MCP Server 的工具清单
    call_tool(name, arguments)    → 调用远程工具
    disconnect()                  → 断开连接

  class MCPToolWrapper implements Tool:
    inner_tool: MCPRemoteTool
    adapter: MCPAdapter
    execute(args):
      return adapter.call_tool(inner_tool.name, args)
```

关键差异：
- **内置工具**在 LLM 沙箱/隔离环境中执行，受安全策略控制
- **自定义工具**（含 MCP 工具）在客户端侧执行，拥有真实系统权限

> v4 建议：MCP 工具优先经 **tool search**（§6）暴露，而非常驻工具区——既扩大生态又不破坏缓存。

### 9. 沙箱与代码执行的安全边界

CodeExecution（§5）与内置工具的隔离执行，都依赖沙箱的三层隔离（文件系统 / 网络 / 进程）。完整设计、资源限额配置、凭证外置与注入模式扫描见 `references/12-sandbox-advanced.md`。本节只强调一点：**代码执行把"N 次带副作用的工具调用"收敛为"一次受控批处理"**，反而缩小了攻击面——前提是沙箱真正独立于 Agent 代码（见 12 的"不可绕过"原则）。

---

## 抽象接口层

> **以下仅定义接口契约和设计意图，不包含可执行的代码实现。AI 应根据这些契约构建具体代码。**

### Tool 接口

```
interface Tool:
    name: string
        // 工具唯一标识，LLM 通过此名调用
    description: string
        // 写给 LLM 的 Prompt 级描述（为 Agent 设计，非人类 API）：
        //   - 功能说明（做什么）
        //   - 使用时机（何时用）
        //   - 反例（何时不用 / 常见误用）  ← 原则 ②a 硬性要求
        //   - 参数说明（每个参数的含义、类型、约束）
        //   - 返回值说明（数据结构、字段含义）
    input_schema: JSONSchema
        // 参数 JSON Schema
    category: ToolCategory
    concurrency_mode: enum { READ_ONLY, WRITE, MIXED }
    dependencies: ToolDependency[]
    lazy: bool
        // 新增（v4）：true = 不进稳定前缀，仅经 tool_search 按需暴露
    execute(args: Dict) -> ToolResult:
        raise NotImplementedError("AI: 实现工具逻辑；
            失败时 error 字段须为纠正性提示而非堆栈（原则 ②b）；
            返回只含 Agent 后续所需最小字段（原则 ②c）")
```

### ToolRegistry 接口

```
interface ToolRegistry:
    register(tool: Tool)
    unregister(name: string)
    get(name: string) -> Tool
    list_all() -> Tool[]                       // 完整目录（含 lazy 工具）
    lightweight_catalog() -> CatalogEntry[]    // 仅 name + one_line_summary，给 LLM 常驻
    get_for_llm(context_hint: string?, limit: int?) -> ToolDefinition[]
        // 返回常驻给 LLM 的工具定义子集（不含 lazy 完整定义）
    search(query: string) -> ToolDefinition[]
        // 新增（v4）：tool search，语义发现并加载 lazy 工具的完整定义
        // 结果作为工具结果返回，不进入缓存前缀
    execute_batch(calls: ToolCall[]) -> ToolResult[]
        // 内部执行分区算法 + 依赖解析
```

### 工具分区调度器（Scheduler）

```
interface ToolScheduler:
    schedule(calls: ToolCall[], config: ConcurrencyConfig) -> SchedulePlan
        // DAG 构建 → 拓扑排序 → 每层按 concurrency_mode 分区
        // 只读并发，写入串行
    truncate_results(results: ToolResult[]) -> ToolResult[]
        // 旧"结果截断"；v4 已被后处理钩子（§7）取代，此处保留为钩子的一环
```

### CodeExecution 接口（v4 新增）

```
interface CodeExecutionTool:
    name: string
    description: string
        // 须含：多步编排任务用；1-3 步、交互式、需中途人类反馈、
        // 需依据中间结果动态选工具 时不用（见 §5 不适用边界）
    sandbox_policy: SandboxPolicy           // 引用 references/12-sandbox-advanced.md
    execute(script: str, lang: str) -> ToolResult:
        raise NotImplementedError("AI: 沙箱内执行 script；
            仅回传最终输出，中间步骤不进上下文；
            执行前做输出扫描检测注入模式；
            超时/超限/检测到注入 均转写为纠正性 error；
            安全边界遵循 references/12-sandbox-advanced.md 三层隔离")
```

---

## AI 构建提示

构建此 Phase 时，AI 应按以下优先级决策（v4 重排）：

### 优先级 1：先定"最小可用集"，再谈扩展

不要一上来铺 10+ 工具。先给 1-3 个强工具跑通，按"先减后加"路径（原则 ①）观察失败点。工具数量上限见规模指南。**默认假设是"这个工具可以砍掉"，除非能论证不可替代。**

### 优先级 2：描述质量 > 实现质量（且描述须含时机与反例）

花 60% 时间在描述上：功能 + 时机 + 反例 + 参数 + 返回。反例直接防住误用（原则 ②a）。**绝不**直接搬运人类 API 描述。

### 优先级 3：错误信息必须可纠正

错误处理层把异常**转写为 LLM 可自我纠正的提示**（原则 ②b），禁止透传堆栈。这是对准确率影响最大却最易忽略的一环。

### 优先级 4：能用代码执行就别发 N 次调用

遇到多步线性数据处理（>3 步、可收敛、无中途人类反馈、无动态分支），优先 CodeExecution（§5），按不适用边界（§5）排除后才用普通多步调用。

### 优先级 5：tool search 暴露大目录，保护缓存前缀

lazy 工具经 `tool_search` 暴露，完整定义不进稳定前缀（§6）。MCP 工具同理（见 `references/10-mcp-integration.md`）。

### 优先级 6：Schema 与实现一致性

Schema 定义了 `param_X`，`execute` 必须读 `param_X`（大小写一致）。编写一致性测试。

---

## 规模适应性指南

### 三档差异总表

| 维度 | Minimal | Professional | Enterprise |
|------|---------|--------------|------------|
| 常驻强工具 | **1-3 个** | **5-8 个**（+ 可选代码执行） | 个位数常驻 + **大工具目录** |
| 工具发现 | 无（全常驻） | 静态核心组即可 | **tool search** + 大目录 |
| 代码执行 | 可选（1 个 `code_exec`） | **可选但推荐** | **沙箱代码执行标配** |
| 分区调度 | 不需要（串行） | 只读并发 + 写入串行 | 完整依赖图 + 并发调度 |
| 后处理钩子 | 简单截断 | 头尾保留 + 摘要 | 全钩子链（truncate/project/dedup/scan） |
| MCP | 不接入 | 1-2 个经 tool search | 多适配器 + tool search 暴露 |
| 沙箱 | 基础 workdir 隔离 | 基础隔离 | 三层隔离 + 资源限额（见 12） |

### Minimal（原型/小项目）

- **工具数量**：**1-3 个强工具**（典型：1 个 `file_io` + 1 个 `code_exec`）。
- **注册表**：简单 Dict/map，无需 Tool 类抽象。
- **并发**：不需要分区，所有工具串行。
- **后处理**：简单按字符数硬截断。
- **代码执行**：可选，一个 `code_exec` 即可覆盖多步需求。
- **tool search**：不需要，工具全常驻。
- **MCP**：不接入。

### Professional（团队项目/正式产品）

- **工具数量**：**5-8 个强工具**；超过 8 个必须论证不可替代性（原则 ①）。
- **注册表**：ToolRegistry 类 + Tool 接口，Schema 验证。
- **并发**：实现分区算法，只读 > 5 个时并发。
- **后处理**：头尾保留 + 中部摘要。
- **代码执行**：**可选但推荐**——多步数据处理用 `code_exec` 替代 N 次调用。
- **tool search**：轻量目录常驻，lazy 工具经 search 暴露（保护缓存）。
- **MCP**：MCPAdapter + tool search 暴露 1-2 个外部工具。

### Enterprise（高可用/多租户/多 Agent）

- **工具数量**：**工具目录可含几十~几百**（含 MCP 生态），但**常驻 LLM 的仍是个位数**，其余经 **tool search** 按需暴露。
- **注册表**：动态注册/注销、工具版本管理、`lazy` 标记管理。
- **并发**：完整依赖图 + 并发调度器 + 最大并发数可配。
- **后处理**：全钩子链（truncate → project → dedup → scan），结果进上下文前压缩。
- **代码执行**：**沙箱代码执行标配**（见 `references/12-sandbox-advanced.md` 三层隔离 + 资源限额 + 注入扫描）。
- **tool search**：核心能力，目录越大收益越高，对 prompt cache 零影响。
- **MCP**：多适配器实例，连接池，断线重连，全部经 tool search 暴露。
- **安全**：内置工具沙箱隔离，自定义/MCP 工具审计日志 + 权限确认。

---

## 检查清单

- [ ] 工具数量是否压到上限内（Min 1-3 / Pro 5-8 / Ent 个位数常驻）？
- [ ] 是否有"先减后加"的调优记录（而非一上来铺满）？
- [ ] 每个工具描述是否含**使用时机 + 反例**（原则 ②a）？
- [ ] 失败时 `error` 是否是**纠正性提示**而非堆栈（原则 ②b）？
- [ ] 工具返回是否只含后续所需最小字段（原则 ②c）？
- [ ] 是否有可合并却拆散的窄工具（原则 ① 合并判据）？
- [ ] 多步线性任务是否优先用了 CodeExecution（§5）？
- [ ] 是否排除了 CodeExecution 的不适用边界（1-3 步/交互/动态分支/不可逆副作用）？
- [ ] lazy 工具是否经 **tool search** 暴露，完整定义不进缓存前缀（§6）？
- [ ] 是否实现了**工具输出后处理钩子**，在进上下文前压缩（§7）？
- [ ] 每个工具的 `input_schema` 是否完整且大小写与 `execute` 一致？
- [ ] 是否标记了 `concurrency_mode`（READ_ONLY / WRITE）？
- [ ] MCP 工具是否经 tool search 暴露（见 `references/10-mcp-integration.md`）？

---

## 常见陷阱

### 陷阱 1：工具描述只写"做什么" → LLM 选错/漏参

**症状**：LLM 选错相似工具、漏填 required 参数。
**根因**：描述缺"使用时机"与"反例"。
**解法**：按"功能 → 时机 → 反例 → 参数 → 返回"写；反例直接划清工具边界（原则 ②a）。

### 陷阱 2：一失败就加工具 → 准确率不升反降

**症状**：Agent 某任务失败，加一个工具，下次换种失败，再加……工具 50+，准确率持续下滑。
**根因**：违背"工具数量与准确率反比"（原则 ③）；多数失败是描述不清或可用代码执行，而非真缺工具。
**解法**：走"先减后加"路径（原则 ①）；先排查描述、再考虑代码执行，最后才加工具。

### 陷阱 3：错误信息透传堆栈 → LLM 无法自愈

**症状**：工具报错 `"KeyError: 'x'"`，LLM 下一轮重复同样错误。
**根因**：`error` 字段是堆栈不是纠正提示（违背原则 ②b）。
**解法**：错误层转写为"你哪里错、正确做法是什么"的自然语言。

### 陷阱 4：延迟加载仍破坏 prompt cache

**症状**：工具多，每次请求上下文被工具定义占 30%+，缓存命中率低。
**根因**：旧方案全发或关键词预筛，都动到缓存前缀。
**解法**：升级 **tool search**（§6）——lazy 工具加 boolean，完整定义只经 search 结果返回，不进稳定前缀。

### 陷阱 5：短任务滥用 CodeExecution

**症状**：1-2 步任务也写脚本执行，延迟与开销反而更高。
**根因**：忽略不适用边界（§5）。
**解法**：1-3 步、交互式、需中途人类反馈、需动态选工具的，退回普通工具调用。

### 陷阱 6：写入工具并发 → 数据竞争

**症状**：3 个 write_file 并发，同文件被覆盖。
**根因**：未标记 `concurrency_mode`。
**解法**：分区算法，写入类强制串行队列。

### 陷阱 7：结果未进上下文前压缩 → Token 浪费

**症状**：8000 行结果全量进上下文，后续 token 不足。
**根因**：截断靠事后四级压缩兜底。
**解法**：后处理钩子（§7）在边界处先 truncate/project/dedup/scan。

### 陷阱 8：沙箱 vs 客户端权限混淆

**症状**：自定义/MCP 工具在客户端有完整权限，误删文件。
**根因**：未区分内置（沙箱）与自定义（客户端）权限边界。
**解法**：内置工具限 workdir；自定义工具加权限确认 + 审计（见 12）。

---

## 下一步

完成 Phase 3 后，进入 **Phase 4: Agent 核心循环**（参考 `references/04-phase-agent-loop.md`）。工具集确定后，核心循环负责在"选工具 / 调工具 / 读结果 / 压缩上下文"之间编排。
