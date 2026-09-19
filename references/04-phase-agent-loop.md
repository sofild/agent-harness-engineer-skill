# Phase 4: Agent核心循环 (v4)

## 目标

设计健壮的Agent主循环——这是Agent系统的**心脏**。v4 版本在 v3 的 `while True` + 状态机 + WAL 日志基础上，将 continue 站点扩展为 **8 个**（原 7 个 + v4 新增的 **CONTINUE-SITE-8：Verification Failure**），并融入 2026 年 Loop Engineering 九大技术，形成可配置、可扩展、可观测的现代 Agent 循环架构。

---

## 设计原理

### 旧版设计的致命缺陷

```
# ❌ 错误的 AgentCore.run()
async def run(self, user_input: str) -> str:
    while True:
        response = await self.llm_client.chat(...)
        if response.tool_calls:
            results = await self._execute_tools(response.tool_calls)
            self.state.messages.append(format(results))
            continue          # 继续循环 —— 看起来没问题
        return response.content  # ❌ 首次无工具调用就退出！
```

**问题**：
- 如果 LLM 返回文本（无 tool_use），run() 立即返回，不再给 LLM 继续思考和调用工具的机会
- 错误恢复粗糙：一个 `except Exception` 包裹整个循环体，无法精细区分恢复策略
- 没有流式事件：调用方阻塞等待整个 `str` 结果，中间状态不可观察
- 没有状态机：无法暂停、续跑、超时控制
- 会话管理耦合在独立类中，缺少 WAL 语义

### 正确设计的核心原则

1. **永不退出**：`while True` 是 Agent 循环的绝对基础，不会有"自然结束"——只有达到终止条件才 `break`
2. **流式事件输出**：使用 `AsyncGenerator` yield 中间事件，调用方可以实时消费进度
3. **状态机驱动**：状态转换明确，每个 continue 站点检查当前状态
4. **8个弹性恢复点**：每种失败模式有专属的恢复策略，按严重程度渐进升级（含 v4 新增的 Verification Failure 站点）
5. **事件日志即真理**：会话事件以 append-only JSONL 形式写入，类比数据库 WAL
6. **声明式配置驱动**：循环拓扑通过 YAML/JSON 声明，策略切换无需改代码（v4 新增）
7. **双层循环解耦**：规划与执行分层，减少无效工具调用，提升复杂任务成功率（v4 新增）
8. **安全护栏包裹**：每个行动前后都经过安全检查子循环（v4 新增）

### 2026 升级总览

本阶段吸收 2026 年 Loop Engineering 九大技术，按三级规模分布：

| # | 技术 | Minimal | Professional | Enterprise |
|---|------|:-------:|:------------:|:----------:|
| 1 | 轻量图 + 代码节点混合架构 | 概念 | 简化版 | 完整实现 |
| 2 | 计划-执行双层循环 + 动态重规划 | ✗ | 简化版 | 完整实现 |
| 3 | 事件驱动与流式循环 | ✗ | 基础流式 | 完整事件总线 |
| 4 | 多 Agent 拓扑循环 | ✗ | ✗ | 完整实现 |
| 5 | 长时持久化与耐久执行 | ✗ | 基础检查点 | Temporal.io 模式 |
| 6 | DSPy 自优化循环 | ✗ | ✗ | 预留接口 |
| 7 | 声明式循环配置 | 字典配置 | YAML 配置 | YAML + 热加载 |
| 8 | 可观测断点与人工协同 | ✗ | 基础日志 | 动态断点 + 热修改 |
| 9 | 安全护栏子循环 | 基础检查 | 简化版 | 完整双层防线 |

**技术选型决策矩阵**：

| 维度 | 推荐方案 | 为什么 |
|------|---------|--------|
| 控制流复杂度 | 轻量图 + 代码节点 | 拓扑可见、逻辑可调试、策略可切换 |
| 任务复杂度 | 双层循环 + 动态重规划 | 复杂任务成功率提升 25%，无效调用减少 50% |
| 延迟敏感 | 流式循环 + 异步事件总线 | 端到端延迟从 9s 降到 3s |
| 质量要求 | Generator-Critic 或多 Agent 辩论 | 质量提升显著，Token 成本可控 |
| 可靠性要求 | Temporal.io 耐久执行 | 服务器崩溃后自动恢复，不丢状态 |
| 持续改进 | DSPy 自优化循环 | 无需人工改 prompt，自动提升 15-35% |
| 工程门槛 | 声明式配置 | 策略即配置，可 Git、可 diff、可实验 |
| 运维可控 | 可观测 Loop + 动态断点 | 运行时注入审批，不下线调整参数 |
| 安全合规 | 安全护栏子循环 | 每个 Action 前后双层防线 |

---

## 抽象接口层

### 1. 状态机定义

```
状态机图（Mermaid 伪代码）:

  ┌──────┐    用户输入     ┌─────────┐
  │ idle │ ───────────────→ │ running │
  └──────┘                  └─────────┘
     ↑                          │  │  │
     │      循环结束             │  │  │
     │  (session_reset)         │  │  │ 达到 max_turns / 超时
     │                          │  │  └──────────────────────→ ┌─────────┐
     │    Stop Hook 阻塞        │  │                            │ expired │
     │    ←─────────────────────┘  │                            └─────────┘
     │                             │
     │   API 不可恢复错误           │  手动暂停
     │   ←─────────────────────────┘  ────────────→ ┌────────┐
     │                                               │ paused │
     │   不可恢复异常                                  └────────┘
     │   ←──────────────────────────────────────────→ ┌───────┐
     │                                                │ error │
     └───────────────────────────────────────────────→ └───────┘
```

> **验证失败回路（CONTINUE-SITE-8）**：行动（工具执行 / 文件写入等）完成后，主循环在 `running` 态内调用 `Verifier.verify()`。若确定性检查失败，把**结构化的失败输出**（文件路径 + 行号 + 错误码）作为 sensor 注入下一轮上下文，循环回到 `running` 重新行动；连续 N 次（默认 3）同一错误则升级为 replan 或 `human_required`，离开 `running` 态。该站点与 `max_turns` / 会话超时 / Budget 检查点同级，都是 `running` 态内的退出/回流分支。

**状态枚举**（抽象类骨架）：

```python
class AgentState(Enum):
    IDLE       = "idle"      # 会话尚未启动，等待首次输入
    RUNNING    = "running"   # 循环正在执行
    PAUSED     = "paused"    # 被外部信号暂停（Stop Hook 触发后）
    EXPIRED    = "expired"   # 达到轮次上限或会话级超时
    ERROR      = "error"     # 不可恢复异常，会话终止
```

**State 对象**（伪代码——仅字段声明，非可运行的实现）：

```python
@dataclass
class AgentRunState:
    """Agent 运行时状态——每次迭代开始时解构，在 continue 站点重新赋值"""
    status: AgentState = AgentState.IDLE

    # 消息历史（不可变追加语义：每次 continue 站点应整体替换而非原地修改）
    messages: List[Dict[str, Any]] = field(default_factory=list)

    # 轮次控制
    turn_number: int = 0
    max_turns: int = 50
    session_started_at: float = 0.0       # time.monotonic()
    session_timeout_seconds: float = 600.0 # 会话级超时（企业级：双重超时）

    # 恢复标志（陷阱：每次 continue 站点必须重置！）
    has_attempted_reactive_compact: bool = False

    # 暂停信号
    pause_requested: bool = False
    resume_callback: Optional[Callable] = None

    # 错误追踪
    last_error_type: Optional[str] = None
    consecutive_errors: int = 0
    max_consecutive_errors: int = 3

    # v4 新增：验证失败追踪（CONTINUE-SITE-8）
    consecutive_verification_errors: int = 0
    max_consecutive_verification_errors: int = 3  # 连续 N 次同一错误 → 升级 replan / human_required

    # v4 新增：预算检查点（Budget 抽象来自 references/06-phase-permissions.md，不在此重定义）
    budget: Optional["Budget"] = None  # 由 Phase 6 注入；轮次上限 / 会话超时 / Budget 三选一先到先停

    # v4 新增：双层循环状态
    execution_plan: Optional["ExecutionPlan"] = None  # 当前执行计划
    loop_config: Optional["LoopConfig"] = None        # 声明式循环配置

    # v4 新增：耐久执行状态
    checkpoint_id: Optional[str] = None   # 当前检查点 ID
    last_checkpoint_at: float = 0.0       # 上次检查点时间
```

### 2. AgentCore 抽象类

> **重要**：以下所有代码片段是**抽象骨架 + 伪代码**，不可直接复制运行。目的是展示接口签名、循环结构和8个 continue 站点的位置关系。

```
# ─── 抽象 AgentCore 骨架 ───
class AgentCore:
    """
    永不退出的 Agent 主循环。

    架构约束:
      - 状态: 单一 AgentRunState 实例，伪不可变（continue 站点必须整体重新赋值）
    - 输出: AsyncGenerator[AgentEvent, None] —— 每个中间状态作为一个事件 yield
    - 恢复: 8个 continue 站点覆盖所有已知失败模式（含 v4 新增的 Verification Failure 站点）
    - 预算: 轮次上限、会话超时、Budget 检查点三选一先到先停（Budget 抽象见 references/06-phase-permissions.md）
    - 日志: SessionEventLog 以 append-only JSONL 持久化，每个事件必须在前才能 yield 给调用方
      - 配置: 支持从 LoopConfig 声明式加载循环策略（v4 新增）
      - 护栏: SafetyGuardLoop 包裹每个行动（v4 新增）
    """

    state: AgentRunState
    event_log: SessionEventLog
    llm_client: BaseLLMClient          # 来自 Phase 2
    tool_registry: ToolRegistry        # 来自 Phase 3
    context_manager: ContextManager    # 来自 Phase 5
    stop_hooks: List[StopHook]         # 来自 Phase 6
    safety_guard: SafetyGuardLoop      # v4 新增 ★技术9
    loop_config: LoopConfig            # v4 新增 ★技术7
    verifier: Verifier                 # v4 新增：确定性验证回路（见下文 §11）
    budget: Budget                     # v4 新增：预算抽象（来自 references/06-phase-permissions.md）

    # ═══════════════════════════════════════════════════════════
    # 主循环（伪代码——展示结构而非可运行实现）
    # ═══════════════════════════════════════════════════════════
    async def run(self, user_input: str) -> AsyncGenerator[AgentEvent, None]:
        """
        永不退出的 Agent 主循环。

        Yield 事件类型:
          - TurnStartEvent     → 每轮开始
          - UserMessageEvent   → 首次用户输入已记录
          - AssistantTextEvent → LLM 返回文本增量（流式）
          - ToolUseEvent       → LLM 请求工具调用
          - ToolResultEvent    → 工具执行结果
          - TurnEndEvent       → 每轮结束
          - StateChangeEvent   → 状态转换（idle→running、running→paused 等）
          - ErrorEvent         → 恢复性错误（非致命）
          - PlanGeneratedEvent → 计划生成（v4 新增）
          - SafetyCheckEvent   → 安全检查结果（v4 新增）
        """

        # === 入口状态验证 ===
        if self.state.status != AgentState.IDLE:
            yield StateChangeEvent("Cannot start: agent is not IDLE")
            return

        self.state.status = AgentState.RUNNING
        self.state.session_started_at = time.monotonic()
        yield StateChangeEvent(old=IDLE, new=RUNNING)

        # 记录首次用户消息
        self.event_log.append(UserMessageEvent(content=user_input))
        self.state.messages = [*self.state.messages, {"role": "user", "content": user_input}]

        # ═══════════════════════════════════════════════════
        #  永不退出的主循环
        # ═══════════════════════════════════════════════════
        while True:
            # ── 0. 前置检查 ──
            # 状态检查：是否被外部暂停
            if self.state.pause_requested:
                self.state.status = AgentState.PAUSED
                yield StateChangeEvent(old=RUNNING, new=PAUSED)
                await self._wait_for_resume()
                self.state.status = AgentState.RUNNING
                yield StateChangeEvent(old=PAUSED, new=RUNNING)

            # v4 新增：热修改检查（可观测断点）
            if self._hot_config_changed():
                self._reload_loop_config()
                yield StateChangeEvent(reason="hot_config_reloaded")

            # v4 新增：动态断点检查
            breakpoint = await self._check_breakpoint()
            if breakpoint:
                yield BreakpointEvent(breakpoint)
                await self._wait_for_breakpoint_resolution(breakpoint)

            # 轮次上限检查
            if self.state.turn_number >= self.state.max_turns:
                self.state.status = AgentState.EXPIRED
                yield StateChangeEvent(old=RUNNING, new=EXPIRED, reason="max_turns_reached")
                break

            # 会话级超时检查（企业级：双重超时的外层）
            elapsed = time.monotonic() - self.state.session_started_at
            if elapsed > self.state.session_timeout_seconds:
                self.state.status = AgentState.EXPIRED
                yield StateChangeEvent(old=RUNNING, new=EXPIRED, reason="session_timeout")
                break

            # v4 新增：预算检查点（与轮次上限、会话超时同级，三选一先到先停）
            # Budget 抽象来自 references/06-phase-permissions.md，此处只调用、不重定义
            if self._budget_exceeded():
                self.state.status = AgentState.EXPIRED
                yield StateChangeEvent(old=RUNNING, new=EXPIRED, reason="budget_exhausted")
                break

            # ── 1. 轮次开始 ──
            self.state.turn_number += 1
            turn_start = time.monotonic()
            self.event_log.append(TurnStartEvent(turn=self.state.turn_number))
            yield TurnStartEvent(turn=self.state.turn_number)

            # v4 新增：耐久执行检查点（每 N 步存档一次）
            if self.state.turn_number % self.loop_config.checkpoint_interval == 0:
                await self._save_checkpoint()

            try:
                # ── 2. 压缩管道（Phase 5 集成点）──
                # 这是 CONTINUE-SITE-1 的调用入口
                self.context_manager.compact(self.state.messages)
                if self.context_manager.was_compacted():
                    yield CompactionEvent(detail=self.context_manager.last_compaction_detail)

                # ── 3. 调用 LLM（流式）──
                # 轮次级超时包装（企业级：双重超时的内层）
                try:
                    async for chunk in self.llm_client.stream_chat(
                        messages=self.state.messages,
                        tools=self.tool_registry.get_definitions(),
                        timeout=self._turn_timeout(),
                    ):
                        if chunk.is_text:
                            self.event_log.append(AssistantTextEvent(content=chunk.delta))
                            yield AssistantTextEvent(content=chunk.delta)
                        response = self._accumulate(chunk)

                except TurnTimeout:
                    self.state.consecutive_errors += 1
                    if self.state.consecutive_errors > self.state.max_consecutive_errors:
                        self.state.status = AgentState.ERROR
                        yield StateChangeEvent(old=RUNNING, new=ERROR, reason="turn_timeout_exhausted")
                        break
                    yield ErrorEvent(type="turn_timeout", turn=self.state.turn_number)
                    continue

                # ── 4. 后处理响应 ──
                self.event_log.append(AssistantTextEvent(content=response.text, is_final=True))

                # ── 5. 处理 tool_use ──
                if response.has_tool_uses:
                    for tool_call in response.tool_uses:
                        self.event_log.append(ToolUseEvent(
                            tool_name=tool_call.name,
                            tool_input=tool_call.input,
                            tool_use_id=tool_call.id,
                        ))
                        yield ToolUseEvent(tool_call)

                    # v4 新增：行动前安全检查
                    for tool_call in response.tool_uses:
                        pre_verdict = await self.safety_guard.pre_action_check(
                            action={"name": tool_call.name, "args": tool_call.input},
                            agent_state={"turn": self.state.turn_number},
                        )
                        if pre_verdict == SafetyVerdict.BLOCK:
                            yield SafetyCheckEvent(phase="pre", verdict="BLOCK", tool=tool_call.name)
                            self.state.messages = [
                                *self.state.messages,
                                {"role": "user", "content": f"Action {tool_call.name} blocked by safety guard. Replan."},
                            ]
                            continue
                        if pre_verdict == SafetyVerdict.REQUIRE_REPLAN:
                            yield SafetyCheckEvent(phase="pre", verdict="REQUIRE_REPLAN", tool=tool_call.name)
                            continue

                    # 执行工具
                    tool_results = []
                    for tool_call in response.tool_uses:
                        try:
                            result = await self.tool_registry.execute(
                                name=tool_call.name,
                                arguments=tool_call.input,
                            )
                            tool_results.append(result)
                            self.event_log.append(ToolResultEvent(
                                tool_use_id=tool_call.id,
                                content=result.content,
                                is_error=result.is_error,
                            ))
                            yield ToolResultEvent(result)
                        except Exception as tool_error:
                            tool_results.append(ErrorResult(tool_call.id, str(tool_error)))
                            self.event_log.append(ToolResultEvent(
                                tool_use_id=tool_call.id,
                                content=str(tool_error),
                                is_error=True,
                            ))

                    # v4 新增：行动后审计
                    for tr in tool_results:
                        post_verdict = await self.safety_guard.post_action_audit(
                            action={"name": tool_call.name},
                            output=str(tr.content),
                        )
                        if post_verdict == SafetyVerdict.BLOCK:
                            yield SafetyCheckEvent(phase="post", verdict="BLOCK")
                            break
                        if post_verdict == SafetyVerdict.REDACT:
                            tr.content = "[REDACTED]"

                    for tr in tool_results:
                        self.state.messages = [
                            *self.state.messages,
                            {"role": "user", "content": str(tr.content)},
                        ]

                    # ── 7a. 行动后确定性验证（CONTINUE-SITE-8 调用入口）──
                    # 用确定性验证包裹概率性智能：compile / lint / type / test / schema
                    # 等计算型检查无需再让 LLM 判断"是否成功"，工具自己知道。
                    verification = await self.verifier.verify(
                        artifact=tool_results,
                        context={
                            "turn": self.state.turn_number,
                            "plan": self.state.execution_plan,
                        },
                    )
                    if not verification.passed:
                        self.state.consecutive_verification_errors += 1
                        if (self.state.consecutive_verification_errors
                                >= self.state.max_consecutive_verification_errors):
                            # 连续 N 次同一错误 → 升级为 replan 或 human_required
                            # （ErrorKind 分类见 references/08-core-concepts.md）
                            self.state.messages = [
                                *self.state.messages,
                                {"role": "user", "content": self._format_verification_sensor(verification)},
                            ]
                            self.state.status = AgentState.EXPIRED
                            yield StateChangeEvent(
                                old=RUNNING, new=EXPIRED,
                                reason="verification_exhausted",
                            )
                            self._emit_turn_end(turn_start)
                            break  # 交还给外层 replan 或人工介入

                        # ★ CONTINUE-SITE-8: Verification Failure
                        # 恢复策略：把结构化失败输出（文件路径 + 行号 + 错误码）作为
                        # sensor 注入下一轮上下文——而不是自然语言"失败了"。
                        self.state.messages = [
                            *self.state.messages,
                            {"role": "user", "content": self._format_verification_sensor(verification)},
                        ]
                        yield ErrorEvent(
                            type="verification_failure",
                            turn=self.state.turn_number,
                            machine_readable=verification.machine_readable_output,
                        )
                        self._emit_turn_end(turn_start)
                        continue

                    # ★ CONTINUE-SITE-7: 正常工具执行完成
                    # ⚠️ 陷阱：has_attempted_reactive_compact 不在此处重置！
                    self.state.consecutive_errors = 0
                    self.state.consecutive_verification_errors = 0
                    self._emit_turn_end(turn_start)
                    continue

                # ── 6. 纯文本响应：触发 Stop Hook 检查 ──
                stop_decision = await self._run_stop_hooks(response.text)

                if stop_decision == StopDecision.STOP:
                    self.state.status = AgentState.IDLE
                    yield StateChangeEvent(old=RUNNING, new=IDLE, reason="stop_hook")
                    yield FinalResponseEvent(text=response.text)
                    self._emit_turn_end(turn_start)
                    break

                elif stop_decision == StopDecision.EXTRA_TURN:
                    # ★ CONTINUE-SITE-5: Stop Hook 阻塞
                    self.state.messages = [
                        *self.state.messages,
                        {"role": "user", "content": stop_decision.extra_prompt},
                    ]
                    yield StateChangeEvent(reason="stop_hook_extra_turn")
                    self._emit_turn_end(turn_start)
                    continue

                else:  # CONTINUE
                    self.state.messages = [
                        *self.state.messages,
                        {"role": "user", "content": "Continue your analysis."},
                    ]
                    self._emit_turn_end(turn_start)
                    continue

            # ═══════════════════════════════════════════════
            #  错误恢复：8 个 continue 站点的恢复逻辑
            #  （CONTINUE-SITE-7 为正常路径；CONTINUE-SITE-8
            #   为行动后确定性验证失败，入口见主循环 7a 段）
            # ═══════════════════════════════════════════════
            except PromptTooLongError as e:
                # ★ CONTINUE-SITE-2: Prompt Too Long (HTTP 413)
                if self.state.has_attempted_reactive_compact:
                    self.context_manager.aggressive_snip(self.state.messages)
                    self.state.has_attempted_reactive_compact = False
                else:
                    self.context_manager.reactive_compact(self.state.messages)
                    self.state.has_attempted_reactive_compact = True

                self.state.messages = self.context_manager.messages
                self.state.consecutive_errors += 1
                yield ErrorEvent(type="prompt_too_long", turn=self.state.turn_number,
                                 action="reactive_compact")
                continue

            except MaxOutputTokensError as e:
                # ★ CONTINUE-SITE-3: Max Output Tokens
                truncated = e.last_message.content
                self.state.messages = [
                    *self.state.messages,
                    {"role": "assistant", "content": truncated},
                    {"role": "user", "content": "Please continue from where you left off."},
                ]
                self.state.consecutive_errors += 1
                yield ErrorEvent(type="max_output_tokens", turn=self.state.turn_number,
                                 action="continue_prompt")
                continue

            except ModelUnavailableError as e:
                # ★ CONTINUE-SITE-4: Fallback Model
                if self.llm_client.has_fallback_model():
                    self.llm_client.switch_to_fallback()
                    yield ErrorEvent(type="model_unavailable",
                                     action="fallback",
                                     from_model=e.primary_model,
                                     to_model=self.llm_client.current_model)
                elif self._should_retry_with_backoff():
                    await asyncio.sleep(self._backoff_delay())
                else:
                    self.state.status = AgentState.ERROR
                    yield StateChangeEvent(old=RUNNING, new=ERROR, reason="model_unavailable")
                    break
                self.state.consecutive_errors += 1
                continue

            except ImageTooLargeError as e:
                # ★ CONTINUE-SITE-6: Image/Media Errors
                self.context_manager.remove_large_image(e.message_index)
                self.state.messages = self.context_manager.messages
                self.state.consecutive_errors += 1
                yield ErrorEvent(type="image_too_large", turn=self.state.turn_number,
                                 action="removed_image", detail=e.message_index)
                continue

            except ContextTooLongError as e:
                # ★ CONTINUE-SITE-1: Proactive Compaction 延迟触发
                self.context_manager.emergency_snip(self.state.messages)
                self.state.messages = self.context_manager.messages
                self.state.has_attempted_reactive_compact = True
                self.state.consecutive_errors += 1
                yield ErrorEvent(type="context_too_long", turn=self.state.turn_number,
                                 action="emergency_snip")
                continue

            except RetriableAPIError as e:
                if self.state.consecutive_errors >= self.state.max_consecutive_errors:
                    self.state.status = AgentState.ERROR
                    yield StateChangeEvent(old=RUNNING, new=ERROR, reason="max_consecutive_errors")
                    break
                await asyncio.sleep(self._backoff_delay())
                self.state.consecutive_errors += 1
                yield ErrorEvent(type="retriable_api_error", turn=self.state.turn_number)
                continue

            except IrrecoverableError as e:
                self.state.status = AgentState.ERROR
                self.state.last_error_type = type(e).__name__
                yield StateChangeEvent(old=RUNNING, new=ERROR, reason=str(e))
                break

    # ═══════════════════════════════════════════════════════════
    #  辅助方法（抽象骨架）
    # ═══════════════════════════════════════════════════════════

    def _emit_turn_end(self, turn_start: float):
        """发出 TurnEndEvent 并重置轮次级标志"""
        elapsed = time.monotonic() - turn_start
        self.event_log.append(TurnEndEvent(turn=self.state.turn_number, duration=elapsed))

    async def _wait_for_resume(self):
        """等待外部 resume 信号——使用 asyncio.Event"""
        ...

    async def _run_stop_hooks(self, response_text: str) -> StopDecision:
        """顺序运行所有 Stop Hook，返回 STOP / EXTRA_TURN / CONTINUE"""
        ...

    def _backoff_delay(self) -> float:
        """指数退避：min(2^consecutive_errors, 60.0) 秒"""
        ...

    def _turn_timeout(self) -> float:
        """计算单轮超时时间（企业级：可以为不同轮次设置不同超时）"""
        ...

    # v4 新增辅助方法
    async def _save_checkpoint(self):
        """保存耐久执行检查点"""
        ...

    def _hot_config_changed(self) -> bool:
        """检查是否发生了热修改"""
        ...

    def _reload_loop_config(self):
        """热加载循环配置"""
        ...

    async def _check_breakpoint(self) -> Optional[Dict]:
        """检查是否有管理面板注入的断点"""
        ...

    # v4 新增：验证失败回路辅助方法

    def _budget_exceeded(self) -> bool:
        """调用 references/06-phase-permissions.md 的 Budget 抽象判断预算是否耗尽"""
        ...

    def _format_verification_sensor(self, report: "VerificationReport") -> str:
        """
        把验证报告格式化为结构化 sensor 文本，注入下一轮上下文。

        关键：注入的是 machine_readable_output（文件路径 + 行号 + 错误码），
        而非自然语言"失败了"。LLM 下一轮直接读到可定位的结构化反馈。
        """
        ...
```

### 3. 轻量图配置引擎（★技术1 + ★技术7）

声明式配置是 v4 的基础设施。用 YAML/JSON 描述循环的拓扑结构，引擎解析配置直接生成运行时。

**核心理念**：策略即配置，换 Loop 策略只需换文件，无需改代码。图拓扑一目了然，节点逻辑用纯代码实现。

```python
"""
轻量图 Loop 配置引擎：JSON/YAML 定义拓扑 + 代码实现节点
"""

from typing import Literal, Optional, Dict, List, Any
from dataclasses import dataclass, field


@dataclass
class LoopNodeConfig:
    """循环节点配置"""
    type: Literal["llm", "code", "condition", "parallel"]
    # llm 节点专用
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None
    # code 节点专用（模块路径，如 "my_project.loop_nodes.execute_step"）
    handler: Optional[str] = None
    # condition 节点专用：路由映射
    routes: Optional[Dict[str, str]] = None
    # 默认下一节点
    next: Optional[str] = None
    # parallel 节点专用：并行子节点列表
    parallel_nodes: Optional[List[str]] = None


@dataclass
class LoopConfig:
    """声明式循环配置 —— 完整描述一个循环策略"""
    # 策略类型
    type: Literal["react", "plan-execute", "maker-checker", "ralph", "debate"] = "react"
    # 图拓扑
    entry: str                                    # 入口节点名
    nodes: Dict[str, LoopNodeConfig]              # 节点映射
    # 循环控制
    max_iterations: int = 50
    stop_conditions: List[Dict] = field(default_factory=list)
    # 模型配置
    models: Dict[str, Dict] = field(default_factory=dict)
    # 子 Agent 配置（多 Agent 拓扑）
    sub_agents: List[Dict] = field(default_factory=list)
    # 安全护栏
    guardrails: Optional[Dict] = None
    # 耐久执行
    persistence: Optional[Dict] = None
    checkpoint_interval: int = 5                   # 每 N 步存档一次
    # 可观测性
    observability: Optional[Dict] = None
    # 人工协同
    human_in_the_loop: Optional[Dict] = None


class LoopConfigEngine:
    """根据 YAML 配置动态生成 Loop 运行时"""

    STRATEGIES = {
        "react": "ReactLoop",
        "plan-execute": "PlanExecuteLoop",
        "maker-checker": "MakerCheckerLoop",
        "ralph": "RalphLoop",
        "debate": "DebateLoop",
    }

    @classmethod
    def from_yaml(cls, config_path: str) -> "BaseLoop":
        """从 YAML 文件加载循环配置并生成运行时"""
        ...

    @classmethod
    def from_dict(cls, config: Dict) -> "BaseLoop":
        """从字典加载循环配置并生成运行时"""
        ...


class LightweightLoop:
    """轻量循环引擎：解析配置，驱动节点执行"""

    def __init__(self, config: LoopConfig):
        self.config = config
        self.state = {"messages": [], "iteration": 0}

    async def run(self, task: str) -> AsyncGenerator[AgentEvent, None]:
        """主循环入口：从 entry 节点开始，按拓扑路由执行"""
        current = self.config.entry
        while current != "END" and self.state["iteration"] < self.config.max_iterations:
            node = self.config.nodes[current]
            if node.type == "llm":
                yield from self._run_llm_node(node)
            elif node.type == "code":
                yield from self._run_code_node(node)
            elif node.type == "condition":
                current = await self._evaluate_condition(node)
                continue
            elif node.type == "parallel":
                yield from self._run_parallel_nodes(node)
            current = self._resolve_next(node)
            self.state["iteration"] += 1

    async def _run_llm_node(self, node: LoopNodeConfig) -> AsyncGenerator[AgentEvent, None]:
        """执行 LLM 节点：调用模型，流式输出"""
        ...

    async def _run_code_node(self, node: LoopNodeConfig) -> AsyncGenerator[AgentEvent, None]:
        """执行代码节点：动态导入 handler 函数并调用"""
        ...

    async def _evaluate_condition(self, node: LoopNodeConfig) -> str:
        """评估条件节点：返回路由目标"""
        ...

    async def _run_parallel_nodes(self, node: LoopNodeConfig) -> AsyncGenerator[AgentEvent, None]:
        """并行执行多个子节点"""
        ...

    def _resolve_next(self, node: LoopNodeConfig) -> str:
        """解析下一节点"""
        ...
```

**声明式配置示例（YAML）**：

```yaml
# loop.yaml —— 声明式 Loop 配置，一行不改代码即可切换策略
version: "2.0"
name: "daily-bug-fixer"

loop:
  type: plan-execute
  max_iterations: 30
  stop_conditions:
    - type: test_pass
    - type: max_cost
      value: 5.0
    - type: no_progress
      consecutive_rounds: 3

tools:
  - name: read_file
    source: builtin
  - name: write_file
    source: builtin
    require_approval: true
  - name: run_tests
    source: mcp
    endpoint: "http://ci-server/mcp/test-runner"

models:
  planner:
    provider: anthropic
    model: claude-sonnet-4-20250514
    temperature: 0.3
  executor:
    provider: openai
    model: gpt-4o
    temperature: 0.5

sub_agents:
  - name: maker
    role: generator
    model: executor
    tools: [read_file, write_file, run_tests]
  - name: checker
    role: evaluator
    model: checker
    tools: [read_file, run_tests]
    independent: true

guardrails:
  pre_action:
    - rule: "block destructive ops on src/"
      action: reject_and_replan
    - rule: "max file write per iteration: 3"
      action: reject_and_replan
  post_action:
    - rule: "check for secrets in output"
      action: redact_and_alert

human_in_the_loop:
  triggers:
    - on: write_file
      paths: ["*.env", "*.key", "config/*"]
      action: await_approval
    - on: cost_exceeded
      threshold: 3.0
      action: notify_and_pause

persistence:
  engine: temporal
  checkpoint_every: 5

observability:
  tracing: langsmith
  metrics:
    - loop_iteration_count
    - tool_call_success_rate
    - cost_per_iteration
```

### 4. 双层循环架构（★技术2）

平铺的 ReAct 循环在复杂任务中暴露了根本缺陷：每一步都是局部最优决策，缺乏全局视野。双层循环将规划（战略）与执行（战术）分离。

```
┌──────────────────────────────────────────────────┐
│               Outer Loop: Planner                 │
│  ┌────────────────────────────────────────────┐  │
│  │  Generate high-level plan with steps        │  │
│  │  Step 1 → Step 2 → Step 3 → Step 4         │  │
│  └──────────────────┬─────────────────────────┘  │
│          │   │   │   │                             │
│          ▼   ▼   ▼   ▼                             │
│  ┌────────────────────────────────────────────┐  │
│  │        Inner Loop: Executor (per step)      │  │
│  │   Perceive → Reason → Act → Observe         │  │
│  │   On failure: signal to Outer Loop          │  │
│  └──────────────────┬─────────────────────────┘  │
│                     │                              │
│                     ▼                              │
│   Dynamic Re-plan based on executor result        │
└──────────────────────────────────────────────────┘
```

**外循环 Planner**：LLM 生成高层计划（步骤列表，带依赖关系）。Planner 不参与执行，仅负责战略。

**内循环 Executor**：逐步执行，每步后将结果反馈给外循环。若某步失败，外循环根据新状态动态修订剩余计划。

这本质上是 **Plan-and-Solve 的增强版**，加上 **ReWOO 的核心思想** —— 把观测（Observation）与推理（Reasoning）脱钩，避免上下文被中间结果污染。

```python
"""
双层循环 Agent：Plan-and-Execute + Dynamic Re-plan
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class PlanStep:
    id: str
    description: str
    depends_on: List[str] = field(default_factory=list)
    status: str = "pending"  # pending | running | success | failed


@dataclass
class ExecutionPlan:
    steps: List[PlanStep]
    current_step_index: int = 0


class DualLoopAgent:
    """
    双层循环：
    - Outer loop: 生成计划 + 当执行失败时动态重规划
    - Inner loop: 逐步执行 + 将结果反馈给 Outer loop
    """

    def __init__(self):
        self.outer_context: List[Dict] = []   # 战略层上下文，保持干净
        self.inner_context: List[Dict] = []   # 战术层上下文，只含当前步骤
        self.plan: Optional[ExecutionPlan] = None

    async def outer_loop(self, task: str) -> AsyncGenerator[AgentEvent, None]:
        """Outer Loop：战略层 —— 规划与重规划"""

        # Phase 1: 生成高层计划
        plan_response = await self._call_llm(
            system=(
                "You are a planner. Break the task into a JSON array of steps. "
                'Each step: {"id": "step_N", "description": "...", '
                '"depends_on": ["step_X"]}. '
                "Steps must be ordered. Only output JSON, no explanation."
            ),
            user=task,
        )
        steps_data = json.loads(plan_response)
        self.plan = ExecutionPlan(steps=[PlanStep(**s) for s in steps_data])
        yield PlanGeneratedEvent(steps=len(self.plan.steps))

        # Phase 2: 逐步执行（Inner Loop 调 outer）
        while self.plan.current_step_index < len(self.plan.steps):
            step = self.plan.steps[self.plan.current_step_index]
            step.status = "running"

            result = await self.inner_loop(step)

            if result["success"]:
                step.status = "success"
                self.plan.current_step_index += 1
                self.outer_context.append({
                    "step": step.id,
                    "summary": result.get("summary", result["output"]),
                })
            else:
                step.status = "failed"
                # 动态重规划：根据失败原因修订剩余计划
                if not await self._replan(step, result["error"]):
                    yield ErrorEvent(type="plan_failed", detail=step.id)
                    return

        yield FinalResponseEvent(text="All steps completed successfully")

    async def inner_loop(self, step: PlanStep) -> Dict:
        """Inner Loop：战术层 —— 单步执行 + 迭代修正"""

        # 准备上下文：只包含当前步骤和已完成步骤的摘要
        inner_context = [
            {"role": "system", "content": f"Execute step: {step.description}"},
            {
                "role": "user",
                "content": f"Previous results: {json.dumps(self.outer_context[-3:])}",
            },
        ]

        for attempt in range(5):
            result = await self._execute_with_tools(inner_context)

            if result["success"]:
                return result

            # 把错误反馈注入下一轮
            inner_context.append({
                "role": "user",
                "content": f"Previous attempt failed: {result['error']}. "
                "Analyze the error and try a different approach.",
            })

        return {"success": False, "error": "Max inner loop iterations reached"}

    async def _replan(self, failed_step: PlanStep, error: str) -> bool:
        """动态重规划：根据执行失败原因修订后续步骤"""

        remaining_steps = self.plan.steps[self.plan.current_step_index + 1:]
        if not remaining_steps:
            return False

        replan_prompt = (
            f"Step '{failed_step.description}' failed with: {error}\n"
            f"Remaining steps to complete the task:\n"
            + "\n".join(f"- {s.description}" for s in remaining_steps)
            + "\n\nRevise or reorder the remaining steps. "
            "If the task is no longer achievable, return empty list."
        )

        response = await self._call_llm(
            system="Revise the plan based on the failure. Output JSON array of steps.",
            user=replan_prompt,
        )

        new_steps = json.loads(response)
        if not new_steps:
            return False

        # 替换后续步骤
        self.plan.steps = (
            self.plan.steps[: self.plan.current_step_index + 1]
            + [PlanStep(**s) for s in new_steps]
        )
        self.plan.current_step_index += 1
        return True

    async def _call_llm(self, system: str, user: str) -> str:
        """简化的 LLM 调用接口"""
        ...

    async def _execute_with_tools(self, context: List[Dict]) -> Dict:
        """简化的工具执行接口"""
        ...
```

**效果**（社区报告数据）：
- 无效工具调用减少约 40-60%
- 复杂多步任务的成功率提升约 25%
- 最长可处理 30+ 步的复杂任务链

### 5. 流式事件总线（★技术3）

传统 Agent Loop 是严格串行："请求 → 完整响应 → 解析 → 执行 → 下一轮"。事件驱动循环把这个范式彻底翻转：LLM 每吐出部分结构化动作的片段，就立刻触发工具调用，工具执行的同时 LLM 还在继续生成。

```
Traditional Loop:
LLM generate ──→ parse tool calls ──→ execute tools ──→ concat ──→ LLM generate ──→ ...
[───── wait ─────][── wait ──][── wait ──]

Event-driven Loop:
LLM streaming ───────────────────────────────────────────→
 ├─→ tool call fragment arrives → async execute tool ──→
 │      ├─→ result event pushed
 ├─→ continue generating ───────────────────────────────→
 │      ├─→ state update triggered
 └─→ more tool calls → async execute ───────────────────→
        └─→ next round decision
```

```python
"""
流式事件总线循环引擎：边生成边执行
"""

import asyncio
import json
from typing import AsyncIterator, Dict, Optional


class AsyncEventBus:
    """异步事件总线 —— 解耦事件生产者和消费者"""

    def __init__(self):
        self._queues: Dict[str, asyncio.Queue] = {}
        self._subscribers: Dict[str, List[callable]] = {}

    async def publish(self, channel: str, event: Dict):
        """发布事件到频道"""
        ...

    async def subscribe(self, channel: str, handler: callable):
        """订阅频道"""
        ...


class StreamingLoopEngine:
    """
    核心机制：
    1. LLM 流式输出 → 实时解析工具调用片段
    2. 工具调用立即异步执行
    3. 工具结果以事件形式推回决策循环
    """

    def __init__(self, event_bus: Optional[AsyncEventBus] = None):
        self.event_bus = event_bus or AsyncEventBus()
        self.pending_tools: Dict[str, asyncio.Task] = {}

    async def run(self, task: str, max_iterations: int = 20) -> AsyncGenerator[Dict, None]:
        """流式循环入口"""

        messages = [{"role": "user", "content": task}]
        accumulated_tool_calls: Dict[int, Dict] = {}

        for iteration in range(max_iterations):
            stream = await self._stream_llm(messages)

            async for chunk in stream:
                delta = chunk.choices[0].delta

                # 纯文本增量
                if delta.content:
                    yield {"type": "text", "content": delta.content}

                # 工具调用增量
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in accumulated_tool_calls:
                            accumulated_tool_calls[idx] = {
                                "id": tc_delta.id or "",
                                "function": {"name": "", "arguments": ""},
                            }

                        if tc_delta.id:
                            accumulated_tool_calls[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                accumulated_tool_calls[idx]["function"]["name"] += tc_delta.function.name
                            if tc_delta.function.arguments:
                                accumulated_tool_calls[idx]["function"]["arguments"] += tc_delta.function.arguments

                        # 关键：参数够完整就立即发起异步执行
                        if self._args_complete(accumulated_tool_calls[idx]):
                            await self._dispatch_tool_async(accumulated_tool_calls[idx])

            # 等待所有待处理的工具调用完成
            results = await self._gather_tool_results()

            # 拼接结果进入下一轮
            messages.append({
                "role": "assistant",
                "tool_calls": list(accumulated_tool_calls.values()),
            })
            for tc_id, result in results.items():
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result,
                })

            accumulated_tool_calls.clear()

            if not results:
                break

    def _args_complete(self, tool_call: Dict) -> bool:
        """判断工具调用参数是否足够完整以开始执行"""
        try:
            json.loads(tool_call["function"].get("arguments", ""))
            return True
        except json.JSONDecodeError:
            return False

    async def _dispatch_tool_async(self, tool_call: Dict):
        """异步派发工具调用，立即返回不阻塞"""
        ...

    async def _gather_tool_results(self) -> Dict:
        """等待所有异步工具调用完成，返回结果"""
        ...

    async def _stream_llm(self, messages) -> AsyncIterator:
        """流式调用 LLM API"""
        ...
```

**端到端延迟对比**：

| 模式 | 3 次工具调用延迟 | 说明 |
|------|----------------|------|
| 传统串行 | LLM(2s) + Tool1(1s) + LLM(2s) + Tool2(1s) + LLM(2s) + Tool3(1s) = **9s** | 严格串行 |
| 流式循环 | max(LLM生成，Tool1+Tool2+Tool3并行) ≈ **3-4s** | 边生成边执行 |

### 6. 多 Agent 拓扑支持（★技术4）

单个 Agent 的循环效能有天花板。在一个更大的循环中嵌套多个 Agent，形成"协作循环"。

```python
"""
多 Agent 拓扑循环 —— 三种经典拓扑的抽象接口
"""


class ManagerWorkerLoop:
    """
    管理者-工人循环：主 Agent 协调多个子 Agent

    Manager 自身运行一个监督循环：
    1. 分析任务，拆解为子任务
    2. 分配给 Worker（创建子循环）
    3. 收集结果，评估质量
    4. 不满意则重新分配
    """

    def __init__(self):
        self.workers: Dict[str, "WorkerAgent"] = {}
        self.task_queue: asyncio.Queue = asyncio.Queue()

    async def manage(self, main_task: str) -> AsyncGenerator[AgentEvent, None]:
        """Manager 的主循环"""
        ...

    async def _decompose(self, task: str) -> List[Dict]:
        """LLM 拆解主任务为子任务列表"""
        ...

    async def _select_worker(self, task: Dict) -> "WorkerAgent":
        """根据子任务特征选择最合适的 Worker"""
        ...

    async def _evaluate(self, task: Dict, result: Dict) -> Dict:
        """评估 Worker 结果，返回 pass + feedback"""
        ...


class GeneratorCriticLoop:
    """
    生成-批评-修正循环

    内环结构：
    Generator → Critic → [PASS] → 输出
                       → [FAIL] → Generator（带批评意见）→ ...
    """

    async def generate(self, task: str, max_rounds: int = 5) -> AsyncGenerator[AgentEvent, None]:
        """生成-批评-修正主循环"""
        ...

    async def _generator(self, task: str, previous_output: str = None, feedback: str = None) -> str:
        """Generator: 高温度 (0.7-0.9)，鼓励创造性"""
        ...

    async def _critic(self, output: str, task: str) -> Dict:
        """Critic: 低温度 (0.0-0.1)，严格评估"""
        ...


class DebateLoop:
    """
    多 Agent 辩论循环

    辩论流程：
    1. 多个 Expert Agent 并行独立回答
    2. 互相审阅对方的回答，提出反驳
    3. 多轮辩论后，Judge Agent 汇总裁决
    """

    async def debate(self, question: str, num_experts: int = 3, rounds: int = 3) -> AsyncGenerator[AgentEvent, None]:
        """辩论主循环"""
        ...

    async def _expert_answer(self, question: str, expert_id: int) -> str:
        """Expert 独立回答"""
        ...

    async def _expert_rebut(self, question: str, my_answer: str, other_answers: List[str], expert_id: int) -> str:
        """Expert 反驳其他专家"""
        ...

    async def _judge(self, question: str, answers: List[str]) -> Dict:
        """Judge 汇总裁决"""
        ...
```

**拓扑选择指南**：

| 拓扑 | Token 成本 | 质量提升 | 适用场景 |
|------|-----------|---------|----------|
| Manager-Worker | 中（子任务并行） | 中 | 大型多文件任务，有明确分工 |
| Generator-Critic | 低（2x 调用） | 高 | 代码生成、文档写作 |
| 多 Agent 辩论 | 高（N×M 轮） | 最高 | 安全审计、设计评审、关键决策 |
| 层级委派 | 中-高 | 中-高 | 大规模系统，需要递归拆解 |

### 7. 耐久执行接口（★技术5）

让 Agent 循环具备"系统重启后继续"的能力。每一步的状态写入持久化存储，工作流引擎能重新唤起并从中断的节点继续循环。

```python
"""
耐久执行接口：检查点 + 崩溃恢复
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class DurableLoopState:
    """持久化的循环状态 —— 每一步都写入持久化存储"""
    task: str
    current_step: int = 0
    max_steps: int = 20
    messages: List[Dict] = field(default_factory=list)
    step_results: List[Dict] = field(default_factory=list)
    checkpoint_id: Optional[str] = None


class CheckpointManager:
    """检查点管理器 —— 管理循环状态的持久化与恢复"""

    def __init__(self, backend: str = "file"):
        """
        backend: "file" | "redis" | "temporal"
        """
        ...

    async def save(self, state: DurableLoopState) -> str:
        """保存检查点，返回 checkpoint_id"""
        ...

    async def load(self, checkpoint_id: str) -> DurableLoopState:
        """从检查点恢复状态"""
        ...

    async def list_checkpoints(self, task_id: str) -> List[str]:
        """列出某任务的所有检查点"""
        ...

    async def cleanup(self, older_than: float):
        """清理过期检查点"""
        ...


class LoopRecovery:
    """循环崩溃恢复 —— 从检查点恢复执行"""

    @staticmethod
    async def recover(checkpoint_id: str, loop: "AgentCore") -> AsyncGenerator[AgentEvent, None]:
        """
        从检查点恢复循环执行。

        恢复流程:
        1. 加载检查点 → 重建 AgentRunState
        2. 重放 SessionEventLog → 重建消息历史
        3. 从最后 turn_end 之后继续执行

        关键约束:
        - 代码必须是确定性的（不能用 random、datetime.now()）
        - 每个 Activity 调用至少是幂等的
        """
        ...
```

**替代方案对比**：

| 引擎 | 适用场景 | 复杂度 | 亮点 |
|------|---------|--------|------|
| **Temporal.io** | 生产级长时任务（数小时-数天） | 中高 | 重放机制、多语言 SDK、可视化管理面板 |
| **Prefect** | 数据管道 + Agent Loop | 中 | Python 原生、观测性优秀 |
| **AWS Step Functions** | 已有 AWS 基础设施的团队 | 中 | 免运维、与 AWS 生态深度集成 |
| **Celery + Redis** | 轻量级、快速原型 | 低 | 部署简单、Python 生态成熟 |

### 8. DSPy 自优化接口（★技术6）

将 Loop 本身当作可优化对象。在循环的各节点定义可学习的签名和模块，利用 DSPy 根据成功/失败日志自动优化提示词和 few-shot 示例。

```
Traditional Loop Engineering:
Human design prompt → Loop run → Human observe failure → Human fix prompt → Loop run → ...

DSPy-driven Loop Engineering:
Human define metrics → Loop run → DSPy auto-collect success/failure logs
                                       ↓
                       Auto-optimize prompts, few-shot, model selection
                                       ↓
                       Loop run (new config) → success rate improved
```

```python
"""
DSPy 驱动的自优化 Loop：让循环内的每个决策节点自动进化
"""


class OptimizableNode:
    """可优化节点 —— 循环中可以被 DSPy 编译器优化的决策点"""

    def __init__(self, name: str, signature_class: type):
        self.name = name
        self.signature = signature_class
        self.training_data: List[Dict] = []

    def record_result(self, input_data: Dict, output: str, success: bool):
        """记录执行结果用于后续训练"""
        ...

    def get_training_examples(self) -> List:
        """获取训练样本"""
        ...


class LoopOptimizer:
    """循环优化器 —— 使用 DSPy 编译器优化循环内各节点"""

    def __init__(self):
        self.optimizable_nodes: Dict[str, OptimizableNode] = {}

    def register_node(self, node: OptimizableNode):
        """注册可优化节点"""
        ...

    def optimize(self, metric: callable, trainset: List) -> "LoopOptimizer":
        """
        使用 BootstrapFewShot 或其他编译器优化所有节点。

        优化维度:
        - Prompt 措辞
        - Few-shot 选择
        - Chain-of-Thought 与否
        - 模型选择
        - 上下文长度
        """
        ...

    def export_optimized_config(self) -> LoopConfig:
        """导出优化后的循环配置"""
        ...
```

**实际效果**（社区报告数据 2026 Q2）：
- 任务成功率在无人工改 prompt 的情况下自动提升 **15-35%**
- 原来需要 5-8 次迭代的任务降至 2-4 次
- 特别适合需要反复执行同一类任务的场景（如每日 CI 修复）

### 9. 安全护栏子循环（★技术9）

在每一个行动前后嵌入一个轻量的安全检查循环，形成"行动前审核 → 行动后审计"的双层防线。

```
┌──────────────────────────────────────────────┐
│               Main Agent Loop                 │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │        Pre-Action Safety Loop          │  │
│  │  Check: permission? budget?            │  │
│  │         compliance?                    │  │
│  │              ↓                         │  │
│  │    PASS → Execute      FAIL            │  │
│  │              ↓           ↓             │  │
│  │          Action    Request replan      │  │
│  └────────────────────────────────────────┘  │
│                      ↓                        │
│  ┌────────────────────────────────────────┐  │
│  │       Post-Action Audit Loop           │  │
│  │  Check: sensitive info leak?           │  │
│  │         compliance?                    │  │
│  │              ↓                         │  │
│  │    PASS → Continue      FAIL           │  │
│  │              ↓            ↓            │  │
│  │        Next Step    Block + Alert      │  │
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

```python
"""
安全护栏子循环：每个 Action 前后的双层安全检查
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Callable


class SafetyVerdict(Enum):
    ALLOW = "allow"
    BLOCK = "block"
    REQUIRE_REPLAN = "require_replan"
    REDACT = "redact"


@dataclass
class SafetyRule:
    name: str
    description: str
    severity: str  # critical | high | medium
    check_fn: Callable


class SafetyGuardLoop:
    """
    安全护栏子循环：
    - 行动前：权限、预算、合规检查
    - 行动后：敏感信息、输出审核
    """

    def __init__(self):
        self.pre_rules: List[SafetyRule] = []
        self.post_rules: List[SafetyRule] = []
        self.safety_log: List[Dict] = []

    def add_pre_rule(self, rule: SafetyRule):
        """添加行动前检查规则"""
        ...

    def add_post_rule(self, rule: SafetyRule):
        """添加行动后审计规则"""
        ...

    async def pre_action_check(self, action: Dict, agent_state: Dict) -> SafetyVerdict:
        """行动前安全检查循环 —— 遍历所有 pre_rules"""

        for rule in self.pre_rules:
            verdict = await rule.check_fn(action, agent_state)

            self.safety_log.append({
                "phase": "pre",
                "action": action.get("name"),
                "rule": rule.name,
                "verdict": verdict.name,
            })

            if verdict == SafetyVerdict.BLOCK:
                await self._alert(f"BLOCKED: {action.get('name')} by rule {rule.name}")
                return SafetyVerdict.BLOCK

            if verdict == SafetyVerdict.REQUIRE_REPLAN:
                return SafetyVerdict.REQUIRE_REPLAN

        return SafetyVerdict.ALLOW

    async def post_action_audit(self, action: Dict, output: str) -> SafetyVerdict:
        """行动后审计循环 —— 遍历所有 post_rules"""

        for rule in self.post_rules:
            verdict = await rule.check_fn(output)

            self.safety_log.append({
                "phase": "post",
                "action": action.get("name"),
                "rule": rule.name,
                "verdict": verdict.name,
            })

            if verdict == SafetyVerdict.BLOCK:
                await self._alert(
                    f"POST-BLOCKED: output of {action.get('name')} flagged by {rule.name}",
                    severity=rule.severity,
                )
                return SafetyVerdict.BLOCK

            if verdict == SafetyVerdict.REDACT:
                output = await self._redact(output, rule.name)

        return SafetyVerdict.ALLOW

    async def _alert(self, message: str, severity: str = "high"):
        """发送安全告警"""
        ...

    async def _redact(self, output: str, rule_name: str) -> str:
        """自动脱敏"""
        ...
```

### 10. 可观测断点接口（★技术8）

通过全链路 tracing 实时监控循环状态，运维人员可以在运行时动态注入断点、热修改策略。

```python
"""
可观测 Loop：全链路 tracing + 动态断点 + 热修改
"""


class ObservableLoop:
    """
    每个节点都被 tracing 追踪。
    运维人员可以在管理面板看到实时状态并注入断点。
    """

    def __init__(self, config: LoopConfig):
        self.config = config
        self.hot_config = HotConfigSource()

    async def run(self, task: str) -> AsyncGenerator[AgentEvent, None]:
        """主循环 —— 每个 iteration 都是一个 trace span"""

        state = {"task": task, "iteration": 0}

        while state["iteration"] < self.config.max_iterations:
            # 检查是否有运维注入的断点
            breakpoint = await self._check_breakpoint(state)
            if breakpoint:
                approval = await self._request_human_approval(breakpoint)
                if not approval["approved"]:
                    yield StateChangeEvent(reason="paused_by_human")
                    return

            # 执行一步
            step_result = await self._execute_step(state)

            # 检查热修改
            new_config = await self.hot_config.get()
            if new_config != self.config:
                self.config = new_config
                yield StateChangeEvent(reason="hot_config_reloaded")

            state["iteration"] += 1

    async def _check_breakpoint(self, state: Dict) -> Optional[Dict]:
        """检查管理面板是否注入了断点"""
        ...

    async def _request_human_approval(self, breakpoint: Dict) -> Dict:
        """向管理面板发送人工审批请求"""
        ...


class BreakpointManager:
    """动态断点管理器"""

    async def inject(self, condition: str, action: str, reason: str):
        """注入断点 —— 在下一步挂起，等待人工确认"""
        ...

    async def remove(self, breakpoint_id: str):
        """移除断点"""
        ...

    async def list_active(self) -> List[Dict]:
        """列出所有活跃断点"""
        ...


class HotConfigSource:
    """热修改配置源 —— 从配置中心实时拉取参数"""

    async def get(self) -> LoopConfig:
        """获取最新配置（从 etcd / Consul / Redis）"""
        ...

    async def watch(self, callback: callable):
        """监听配置变更"""
        ...
```

### 11. Verifier 抽象（确定性验证回路 / Guides & Sensors）★v4 新增

**何时读本节**：当你要回答"Agent 写完代码 / 改完配置后，怎么知道它真的对了"时使用本节。核心论断是 **2026 harness 工程的第一性原则——用确定性验证包裹概率性智能**：TypeScript 编译器报 TS2345，不需要再找一个 LLM 来判断"编译是否成功"，编译器自己知道。lint、类型检查、测试、结构分析都是围绕 Agent 的**快速确定性反馈机制**。

**Martin Fowler 的 guides-and-sensors 模型**（本节的理论底座）：
- **guides**（行动**前**影响 Agent）：AGENTS.md、架构文档、代码规范、API 文档、安全策略——它们是"应该怎么写"的指引。
- **sensors**（行动**后**告诉 Agent 发生了什么）：编译错误、测试失败、lint 告警、运行时日志、浏览器结果、安全扫描——它们是"刚才写的对不对"的反馈。
- 最强的 harness 同时具备**计算型控制**（lint / type / test）与**推断型控制**（AI code review）。两类 sensor 都在行动后回喂，区别只在于"谁来判断"。

```python
"""
Verifier：行动后确定性验证回路的抽象接口。
注意：以下为抽象骨架 + 伪代码，不可直接运行。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class VerificationKind(Enum):
    """验证器种类——区分计算型与推断型（见下文明确定位）"""
    COMPUTATIONAL = "computational"  # 确定性：compile / lint / type / test / schema
    INFERENTIAL = "inferential"      # 概率性：LLM-based 主观维度评审


@dataclass
class VerificationReport:
    """验证报告——必须是机器可解析的，才能回喂 LLM 下一轮"""
    passed: bool
    kind: VerificationKind
    findings: List[Dict[str, Any]] = field(default_factory=list)
    # 机器可读输出：结构化失败定位（文件路径 + 行号 + 错误码）
    # 这是 CONTINUE-SITE-8 注入下一轮上下文的载荷
    machine_readable_output: Dict[str, Any] = field(default_factory=dict)


class Verifier:
    """
    行动后验证抽象。

    架构约束（铁律）:
      - 计算型优先：能用 compile/lint/type/test/schema 代码化的检查，
        绝不交给 LLM 判断（编译器自己知道结果，且确定、即时、免费）。
      - 推断型只用于无法代码化的主观维度（代码可读性、架构契合度、
        安全语义判断），且不得作为"最终评判者"。
      - 生成者不得作为自己产出的最终评判者（硬约束，详见
        references/09-multi-agent.md 的 Evaluator 角色）：
        Generator 产出的 artifact 必须由独立 Verifier / Evaluator 校验，
        禁止 self-verify。

    硬约束依据:
      Anthropic 的 Planner → Generator → Evaluator 三段式强制分离，
      理由是"Agent 天然是过于乐观的自我评估者"。实测对照：solo agent
      做复古游戏机项目花了 9 小时但失败；加上 Evaluator 子 agent 的完整
      harness 跑了 6 小时，产出了可工作的软件。
    """

    async def verify(
        self, artifact: Any, context: Dict[str, Any]
    ) -> VerificationReport:
        """
        对 artifact（工具结果 / 文件 / 计划）执行验证。

        Args:
            artifact: 待验证对象（通常是 CONTINUE-SITE-7 产出的 tool_results）
            context:  运行上下文（turn_number、execution_plan 等）

        Returns:
            VerificationReport{passed, findings[], machine_readable_output}
            —— 必须机器可解析，供 CONTINUE-SITE-8 直接注入下一轮。
        """
        raise NotImplementedError("AI: 实现验证逻辑——先跑计算型检查，"
                                   "必要时再跑推断型检查，并组装 machine_readable_output")
```

**计算型 vs 推断型定位**：

| 维度 | 计算型（Computational） | 推断型（Inferential） |
|------|------------------------|----------------------|
| 判断者 | 编译器 / linter / test runner / schema validator | LLM-based reviewer |
| 确定性 | 确定（同输入同结果） | 概率（可能不一致） |
| 延迟 / 成本 | 低（毫秒~秒，免费或极廉） | 高（需多一次 LLM 调用） |
| 适用 | compile / lint / type / unit / schema / 安全扫描 | 可读性、架构契合、安全语义等主观维度 |
| 是否可作为最终评判 | 是（且应优先） | 否——只能作为辅助信号 |

**三级规模差异（Verifier 落地）**：

| 维度 | Minimal | Professional | Enterprise |
|------|:-------:|:-----------:|:----------:|
| 计算型检查 | 仅 `compile` / `run_tests` 占位 | compile + lint + type + unit | 全链路：compile→lint→type→unit→integration→架构检查→安全扫描（见 `references/07-phase-production.md` 确定性门禁清单） |
| 推断型检查 | 无 | 可选 AI code review（轻量） | 独立 Evaluator 子 agent（强制分离，见 09） |
| 生成者自评约束 | 不强制（单 Agent） | 建议独立 reviewer | **强制**：Generator ≠ Evaluator |
| 输出回喂 | 文本日志 | 结构化 findings 注入上下文 | 结构化 + 聚合到可观测系统 |

**AI 构建提示**：
- "实现 `Verifier.verify()`：先同步运行计算型检查（compile / lint / type / test），任一失败则 `passed=False` 并填充 `machine_readable_output`（含 file / line / error_code）；只有计算型全过时，才调用可选的 LLM reviewer 处理主观维度。"
- "确保 `machine_readable_output` 是 dict / JSON，而不是一段自然语言——它会被 CONTINUE-SITE-8 原样注入下一轮 user 消息。"
- "在 Enterprise 规模，把推断型评审实现为 `references/09-multi-agent.md` 中的 Evaluator 子 agent，绝不要让 Generator 调用 `self.verify()` 判定自己。"

---

## AI 构建提示

### 8个 Continue 站点深度说明

| # | 站点名称 | 触发条件 | 恢复策略 | 恢复后状态 | 关键陷阱 |
|---|---------|---------|---------|-----------|---------|
| 1 | **Proactive Compaction** | 上下文 token 数超过安全阈值（如 80%） | 调用四级压缩管道，在 LLM 调用前主动缩减消息 | 消息历史被压缩后，同一轮内用压缩后消息重试 | 压缩可能丢失关键上下文；需要保留系统消息和最近的 tool_use 对 |
| 2 | **Prompt Too Long** | LLM API 返回 413（或 Anthropic 的 `prompt_too_long` 错误码） | 先尝试 reactive compaction；若已尝试则升级为 aggressive snip | 整体替换消息历史，hasAttemptedReactiveCompact 置为 True 后重试 | 压缩失败后容易死循环；需要设置 hasAttemptedReactiveCompact 防止无限尝试 |
| 3 | **Max Output Tokens** | LLM 响应的 `stop_reason == "max_tokens"` 或 `finish_reason == "length"` | 在消息历史末尾追加 "(continue)" 提示词 | 同一轮延续对话，让 LLM 从截断点继续 | 如果 LLM 反复触发此站点，最终会耗尽轮次上限 |
| 4 | **Fallback Model** | 主模型返回 503、超配额、或返回模型不可用错误 | 切换到配置的备选模型（如 Claude Haiku → Claude Sonnet） | 模型客户端内部切换后重试 | 备选模型可能有不同的上下文窗口大小和工具支持 |
| 5 | **Stop Hook Blocking** | 至少一个 Stop Hook 返回 `EXTRA_TURN` 决策 | 将 Hook 指定的额外 prompt 追加到消息历史 | 新轮次开始，给 LLM 额外机会响应 | Stop Hook 自身不能执行耗时操作；它只做判断，不做副作用 |
| 6 | **Image/Media Errors** | 发送的图片超过模型尺寸限制（如 Anthropic 的 `image_too_large`） | 从指定索引的消息中移除/压缩问题图片 | 移除图片后的消息历史重试 | 移除图片后语义可能改变；需要通知调用方图片已被剥离 |
| 7 | **Tool Execution** | LLM 返回 `stop_reason == "tool_use"`，要求调用工具 | 执行工具并将结果追加到消息历史 | 新轮次开始，LLM 接收工具结果继续推理 | 这是正常的循环路径，不是"错误"；但需要重置 consecutive_errors 计数器 |
| 8 | **Verification Failure** | 行动后 `Verifier.verify()` 确定性检查返回失败（compile / lint / type / test / schema 等） | 把结构化失败输出（文件路径 + 行号 + 错误码）作为 sensor 注入下一轮；连续 N=3 次同一错误升级 replan / human_required | 循环回到 running 重新行动；超限则离开 running，交还外层 replan 或人工介入 | 不要注入自然语言"失败了"；验证报告必须是 machine_readable，可被 LLM 下一轮直接消费 |

### 恢复策略升级链

```
检测到问题
    │
    ├─→ 站点1: Proactive Compaction (主动，在 LLM 调用前)
    │      │  成功 → 继续
    │      └─→ 失败
    │            │
    ├─→ 站点2: Reactive Compact (被动，413 错误触发)
    │      │  首次 → hasAttemptedReactiveCompact = True
    │      └─→ 再次触发 → aggressive_snip
    │
    ├─→ 站点3: Max Output → 追加 continue prompt
    ├─→ 站点4: Fallback Model → 模型降级
    ├─→ 站点5: Stop Hook → 追加额外轮次
    ├─→ 站点6: Image Error → 移除问题媒体
    └─→ 站点7: Tool Execution → 正常循环
```

### ErrorKind 映射表（与 08 联动）

每个 continue 站点本质上对应 `references/08-core-concepts.md` 定义的五类 `ErrorKind` 之一：**retryable（可重试）/ fatal（致命）/ degrade（降级）/ replan（需重规划）/ human_required（需人工）**。下方只做映射与理由说明，分类的权威定义以 08 为准。

| # | 站点 | 对应 ErrorKind | 为什么 | 本文件中的处理 |
|---|------|---------------|--------|----------------|
| 1 | Proactive Compaction | `degrade` | 上下文超限不是错误，是主动降级以保住循环 | 压缩后同轮重试，不计入致命 |
| 2 | Prompt Too Long | `retryable` → 失败转 `degrade` | 413 可经压缩恢复；压缩失败才降级 | reactive / aggressive 两级降级 |
| 3 | Max Output Tokens | `retryable` | 追加 continue 即可续写，确定可恢复 | continue prompt 续写 |
| 4 | Fallback Model | `degrade` | 主模型不可用，降级到备选模型继续 | 模型切换后重试 |
| 5 | Stop Hook Blocking | `replan` | Hook 要求额外轮次，等价于局部重规划 | 注入 extra_prompt 重跑 |
| 6 | Image/Media Errors | `retryable` | 移除问题媒体后通常可恢复 | 剥离媒体重试 |
| 7 | Tool Execution | （正常路径，非 ErrorKind） | 不是失败，是循环的正常推进 | 重置计数器，进入下一轮 |
| 8 | Verification Failure | `replan` → 连续 N 次转 `human_required` | 确定性检查失败需改方案；反复失败说明需人工/重规划 | 注入结构化 sensor；超限升级（见 08） |

> 注意：站点 8 的升级终点 `human_required` 与 08 的 `human_required` 语义一致——连续同一验证错误 N 次后，Agent 不应继续空转，应把结构化失败输出交给人工或外层 replan。

### AsyncGenerator 流式模式

Agent 循环不返回最终结果字符串，而是 yield 事件流：

```python
# 调用方代码（伪代码）
async for event in agent.run(user_input="分析这个项目"):
    match event:
        case TurnStartEvent(turn=n):
            print(f"第 {n} 轮开始...")
        case AssistantTextEvent(content=delta, is_final=False):
            print(delta, end="", flush=True)       # 流式打字效果
        case ToolUseEvent(tool_name=name):
            print(f"\n调用工具: {name}")
        case ToolResultEvent(is_error=True):
            print(f"工具错误")
        case ErrorEvent(action=action):
            print(f"自动恢复: {action}")
        case SafetyCheckEvent(phase=phase, verdict=v):
            print(f"安全检查({phase}): {v}")
        case PlanGeneratedEvent(steps=n):
            print(f"已生成 {n} 步执行计划")
        case FinalResponseEvent(text=result):
            print(f"完成")
```

### 轻量图配置使用指南

**选择合适的循环策略**：

```bash
# 策略 A：ReAct（简单任务）
agent loop --config loops/react-config.yaml task.md

# 策略 B：Plan-Execute（复杂多步任务）
agent loop --config loops/plan-execute-config.yaml task.md

# 策略 C：Maker-Checker（质量要求高的任务）
agent loop --config loops/maker-checker-config.yaml task.md

# 对比三者的成功率、耗时、成本
agent loop compare --configs loops/*.yaml --task task.md
```

### 双层循环使用指南

**何时使用双层循环**：
- 任务涉及 5+ 个独立步骤
- 步骤之间有依赖关系
- 预期会有部分步骤失败需要重规划
- 需要减少无效工具调用

**何时用单层 ReAct**：
- 简单查询（1-3 个工具调用即可完成）
- 探索性任务（计划本身会动态变化）
- 延迟敏感（双层循环有额外的规划开销）

### 多 Agent 拓扑选择指南

```
选择流程:
1. 任务是否需要多视角？ → 是 → 多 Agent 辩论
2. 任务是否可分解为独立子任务？ → 是 → Manager-Worker
3. 输出质量要求高但不需要多视角？ → 是 → Generator-Critic
4. 其他情况 → 单 Agent 双层循环或 ReAct
```

### 声明式配置切换指南

**YAML 配置文件结构**：

```yaml
# loop.yaml 最小配置
version: "2.0"
loop:
  type: plan-execute      # 策略类型
  max_iterations: 30       # 最大迭代次数
  stop_conditions:         # 停止条件
    - type: test_pass
    - type: max_cost
      value: 5.0

tools:                     # 工具集
  - name: read_file
    source: builtin
  - name: run_tests
    source: mcp

models:                    # 模型配置
  planner:
    model: claude-sonnet-4-20250514
    temperature: 0.3
  executor:
    model: gpt-4o
    temperature: 0.5
```

---

## 会话事件日志设计

### 设计原则

**类比数据库 WAL (Write-Ahead Log)**：事件必须先写入持久化存储（WAL），然后才能 yield 给调用方。这保证了即使进程崩溃，会话历史也可以从日志文件中完整重建。

### 事件类型

| 事件类型 | 触发时机 | 必填字段 | v4 新增 |
|---------|---------|---------|:-------:|
| `user_message` | 用户发送新的输入 | `content` | |
| `assistant_text` | LLM 返回文本（流式块或最终块） | `content`, `is_final` | |
| `tool_use` | LLM 请求调用工具 | `tool_name`, `tool_input`, `tool_use_id` | |
| `tool_result` | 工具执行返回结果 | `tool_use_id`, `content`, `is_error` | |
| `turn_start` / `turn_end` | 每轮开始/结束 | `turn_number`, `timestamp` | |
| `plan_generated` | 双层循环生成执行计划 | `steps_count`, `plan_json` | ★ |
| `safety_check` | 安全护栏检查结果 | `phase`(pre/post), `verdict`, `rule` | ★ |
| `checkpoint` | 耐久执行检查点保存 | `checkpoint_id`, `step_number` | ★ |
| `breakpoint` | 动态断点触发 | `condition`, `action` | ★ |
| `config_reload` | 热修改配置 | `old_config_hash`, `new_config_hash` | ★ |

### JSONL 格式规范

```
# 文件路径: memory/sessions/{session_id}.jsonl
# 每行一条完整的 JSON 记录，不换行
# append-only：只追加，从不修改或删除

{"type":"turn_start","turn_number":1,"ts":1716220800.123}
{"type":"user_message","content":"分析这个项目","ts":1716220800.150}
{"type":"plan_generated","steps_count":4,"ts":1716220801.000}
{"type":"assistant_text","content":"我来分析...","is_final":false,"ts":1716220801.200}
{"type":"safety_check","phase":"pre","verdict":"ALLOW","rule":"permission_check","ts":1716220801.300}
{"type":"tool_use","tool_name":"read_file","tool_input":{"path":"src/main.py"},"tool_use_id":"tool_001","ts":1716220801.500}
{"type":"tool_result","tool_use_id":"tool_001","content":"import...","is_error":false,"ts":1716220802.100}
{"type":"safety_check","phase":"post","verdict":"ALLOW","rule":"no_secrets","ts":1716220802.200}
{"type":"assistant_text","content":"文件内容显示...","is_final":true,"ts":1716220803.000}
{"type":"checkpoint","checkpoint_id":"ckpt_005","step_number":5,"ts":1716220803.010}
{"type":"turn_end","turn_number":1,"duration":2.9,"ts":1716220803.010}
```

### 不可变性与回放

```python
class SessionEventLog:
    """
    会话事件日志 —— 追加不可变日志。

    设计约束:
      - __init__ 时创建或打开 .jsonl 文件句柄
      - append(event) → 先写入文件、再追加到内存列表、再 yield 事件
      - 没有 delete / update / truncate 操作
      - 支持 replay(session_id) → 重放所有事件以重建 AgentState

    回放算法（伪代码）:
      for line in open(f"{session_id}.jsonl"):
          event = json.loads(line)
          match event.type:
              case "user_message" | "assistant_text":
                  state.messages.append({"role": ..., "content": event.content})
              case "tool_use":
                  pending_tool_uses.add(event.tool_use_id)
              case "tool_result":
                  state.messages.append({"role": "user", "content": event.content})
              case "plan_generated":
                  state.execution_plan = PlanStep.from_json(event.plan_json)
              case "checkpoint":
                  state.last_checkpoint = event.checkpoint_id
              case "turn_end":
                  state.turn_number = event.turn_number
    """
```

### 耐久执行与检查点

**检查点保存时机**：
- 每 N 轮后（由 `checkpoint_interval` 配置）
- 执行计划发生变更时（动态重规划后）
- 安全护栏触发 BLOCK 或 REQUIRE_REPLAN 时
- 人工断点触发前

**崩溃恢复流程**：

```
1. 新 Harness 实例启动
2. 加载最近的检查点 → 重建 AgentRunState
3. 从检查点时间戳之后重放 SessionEventLog → 补全消息历史
4. 从最后 turn_end 之后继续执行
5. 如果 LLM 调用是确定性的（相同输入 → 相同分布输出），则无状态丢失
```

---

## 规模适应性指南

### Minimal（演示/原型 ~80 行核心逻辑）

```
特征:
  - 简单 while True 循环
  - 一个 broad except Exception 捕获所有错误
  - 无重试：catch → 记录日志 → break
  - 无状态机（只区分"运行中"和"已终止"）
  - 无流式输出（async def run() -> str）
  - 无会话日志
  - v4 新增: 字典配置循环参数（max_iterations, stop_conditions）
  - v4 新增: 基础安全检查点（命令黑名单）

适用场景: 一次性脚本、本地测试、快速原型

伪代码骨架:
  config = {"max_iterations": 10, "stop_on": ["test_pass"]}
  while True:
      try:
          response = await llm.chat(messages, tools)
          if response.has_tool_uses:
              # 基础安全检查
              for tc in response.tool_uses:
                  if tc.name in BLOCKED_TOOLS:
                      continue
              results = execute_tools(response.tool_uses)
              messages.extend(format(results))
              continue
          return response.text
      except Exception:
          break
```

### Professional（生产可用 ~400 行核心逻辑）

```
特征:
  - 完整 8 个 continue 站点（含 Verification Failure 站点）
  - 状态机：idle / running / expired / error（无 paused）
  - 指数退避重试（consecutive_errors 计数器 + max_consecutive_errors 上限）
  - 轮次上限 + 单级超时
  - 半流式：yield TurnStart/TurnEnd/Error 事件，文本块做简单的 yield
  - SessionEventLog 写入本地 .jsonl
  - hasAttemptedReactiveCompact 标志（注意重置时机）
  - v4 新增: 轻量图配置引擎（简化版，支持 ReAct / Plan-Execute 切换）
  - v4 新增: 双层循环（简化版，无动态重规划，固定计划执行）
  - v4 新增: 声明式配置（YAML 文件 → LoopConfigEngine.from_yaml()）
  - v4 新增: 安全护栏子循环（简化版：pre-action 权限检查 + post-action 敏感信息扫描）
  - v4 新增: 基础检查点（每 5 轮文件存档）

适用场景: 内部工具、CLI 应用、辅助开发

关键添加强化点:
  - 将 "metadata" 或 "__system__" 消息适配到各提供商的 API 格式
  - 工具调用并行化（并发安全工具同时执行）
  - consecutive_errors 计数器在站点7（正常工具完成）处重置
  - 循环策略可通过 YAML 配置切换（react ↔ plan-execute）
```

### Enterprise（高可用系统 ~800 行核心逻辑）

```
特征:
  - AsyncGenerator 完整流式模式：每个内部事件都 yield
  - 双重超时：turn_level_timeout + session_level_timeout
  - 完整的五状态机含 PAUSED（支持暂停/续跑/迁移）
  - 会话回放：从 .jsonl 重建完整 AgentState
  - 模型降级链：primary → fallback1 → fallback2
  - 错误事件聚合到监控系统（Prometheus / Datadog 指标）
  - 分布式会话：Redis 存储状态 + S3 存储事件日志
  - 消息去重：tool_use_id 去重防止重试时重复执行副作用工具
  - v4 新增: 完整轻量图配置引擎（支持所有节点类型：llm/code/condition/parallel）
  - v4 新增: 完整双层循环 + 动态重规划
  - v4 新增: 流式事件总线（AsyncEventBus + StreamingLoopEngine）
  - v4 新增: 多 Agent 拓扑（Manager-Worker / Generator-Critic / Debate）
  - v4 新增: 耐久执行（Temporal.io 模式 CheckpointManager + LoopRecovery）
  - v4 新增: DSPy 自优化预留接口（OptimizableNode + LoopOptimizer）
  - v4 新增: 声明式配置 + 热加载（YAML + HotConfigSource）
  - v4 新增: 可观测断点（ObservableLoop + BreakpointManager + 人工审批）
  - v4 新增: 完整安全护栏子循环（pre-action + post-action 双层防线）

适用场景: 面向客户的产品、高可用服务、需要审计追踪的系统

企业级额外约束:
  - WAL-before-yield 保证：事件先 fsync 再 yield
  - 会话迁移：序列化 AgentRunState → 另一进程恢复
  - 熔断器：如果 same_error 连续出现 N 次，主动 expire
  - Canary 发布：新模型先作为 fallback，逐步提升为 primary
  - 安全护栏日志不可删除：审计追踪完整保留
```

---

## 检查清单

- [ ] 主循环是真正的 `while True`，不会在首次文本响应时退出
- [ ] 8个 continue 站点全部有专属的错误类型匹配（不是通用的 `except Exception`）
- [ ] `has_attempted_reactive_compact` 在站点2触发前检查，防止 dead loop
- [ ] `consecutive_errors` 在站点7（正常工具执行）后重置为 0
- [ ] `consecutive_verification_errors` 在站点7（验证通过）后重置为 0
- [ ] CONTINUE-SITE-8：行动后有 `Verifier.verify()` 调用，失败时将**结构化** sensor 注入下一轮（非自然语言）
- [ ] 连续 N=3 次同一验证错误会升级为 replan / `human_required`（对应 `references/08-core-concepts.md`）
- [ ] 状态机状态转换合法（idle→running→{idle|expired|error}，running→paused→running）
- [ ] 会话超时使用 `time.monotonic()` 而非 `time.time()`（不受系统时钟调整影响）
- [ ] 流式响应时 `assistant_text` 块正确累积（不能丢失，不能重复）
- [ ] 工具结果以"整体替换"语义追加到 `state.messages`（不原地修改）
- [ ] Stop Hook 内部不执行网络调用、文件 I/O、或其他重量操作
- [ ] SessionEventLog 是 append-only，事件先写盘再 yield
- [ ] 轮次上限、会话级超时、Budget 检查点都作为 break 条件检查（三选一先到先停）
- [ ] 备选模型（fallback）有匹配的上下文窗口和工具支持
- [ ] v4 新增: 声明式配置可以正确切换 ReAct / Plan-Execute / Maker-Checker 策略
- [ ] v4 新增: 双层循环的 Outer/Inner 上下文正确隔离
- [ ] v4 新增: 安全护栏子循环的 pre_action_check 和 post_action_audit 都被调用
- [ ] v4 新增: 安全检查结果正确记录到 SessionEventLog
- [ ] v4 新增: 耐久执行检查点按配置的间隔保存
- [ ] v4 新增: 热修改配置变更后循环参数正确更新
- [ ] v4 新增: 动态断点触发后正确等待人工审批

---

## 常见陷阱

### 陷阱1：`hasAttemptedReactiveCompact` 不重置

```python
# ❌ 错误：在 while 循环顶部重置标志
self.state.has_attempted_reactive_compact = False  # 每轮都重置 → 可能死循环

# 正确：该标志是跨轮次的持久保护
#    - 在站点2（Prompt Too Long）触发时设置 True
#    - 仅在 aggressive_snip 成功后重置 False（因为我们用了不同的策略）
#    - 不在普通循环点重置 —— 它的存在意义就是"防止同一错误反复触发同样的恢复"
```

### 陷阱2：在 Stop Hook 中执行重量操作

```python
# ❌ 错误：Stop Hook 中执行网络调用
class AuditStopHook:
    async def check(self, response_text: str) -> StopDecision:
        audit_result = await self.audit_api.check(response_text)  # 网络调用！
        if audit_result.needs_revision:
            return StopDecision.EXTRA_TURN
        return StopDecision.STOP

# ✅ 正确：Hook 只做逻辑判断，副作用留给下一轮
class AuditStopHook:
    async def check(self, response_text: str) -> StopDecision:
        if self._has_sensitive_pattern(response_text):
            return StopDecision.EXTRA_TURN(prompt="请审计上一轮的输出")
        return StopDecision.STOP
```

### 陷阱3：流式块丢失——累积逻辑错误

```python
# ❌ 错误：只 yield 不累积
async for chunk in llm.stream(messages):
    yield AssistantTextEvent(content=chunk.delta)

# ✅ 正确：同时累积和 yield
accumulated = []
async for chunk in llm.stream(messages):
    accumulated.append(chunk.delta)
    yield AssistantTextEvent(content=chunk.delta)
response.text = "".join(accumulated)
```

### 陷阱4：状态原地修改导致回滚困难

```python
# ❌ 错误
self.state.messages.append({"role": "user", "content": tool_result})

# ✅ 正确：整体替换（伪不可变语义）
self.state.messages = [*self.state.messages, {"role": "user", "content": tool_result}]
```

### 陷阱5：忘记检查暂停信号

在 while 循环中的多个 continue 站点之间，如果 Agent 执行了预先插件化的工作流（如 MCP 工具链），可能花费数分钟。在此期间外部可能已经发送了 pause 信号。解决：在长耗时操作之前/之后主动检查 `self.state.pause_requested`。

### 陷阱6：双层循环上下文污染（v4 新增）

```python
# ❌ 错误：把 Inner Loop 的脏上下文混入 Outer Loop
self.outer_context.extend(self.inner_context)  # 污染了战略层！

# ✅ 正确：Inner Loop 只返回摘要给 Outer Loop
result = await self.inner_loop(step)
self.outer_context.append({
    "step": step.id,
    "summary": result.get("summary", ""),  # 只传摘要
})
```

### 陷阱7：安全护栏阻塞正常流程（v4 新增）

```python
# ❌ 错误：pre_action_check 返回 BLOCK 后没有给 Agent 重新规划的机会
if pre_verdict == SafetyVerdict.BLOCK:
    break  # 直接终止，但任务可能可以通过其他方式完成

# ✅ 正确：注入拒绝原因，让 Agent 尝试替代方案
if pre_verdict == SafetyVerdict.BLOCK:
    self.state.messages = [
        *self.state.messages,
        {"role": "user", "content": f"Action {action['name']} blocked. Try a different approach."},
    ]
    continue  # 回到循环让 LLM 重新规划
```

### 陷阱8：声明式配置与代码逻辑不一致（v4 新增）

```python
# ❌ 错误：配置中声明了 plan-execute 策略，但代码中写死了 ReAct 逻辑
config = LoopConfig.from_yaml("loop.yaml")  # type: plan-execute
# 但代码中:
if response.has_tool_uses:
    ...  # 按 ReAct 方式处理，忽略了 config.type

# ✅ 正确：使用配置引擎生成策略对应的运行时
loop = LoopConfigEngine.from_yaml("loop.yaml")
# 运行时自动根据 config.type 选择正确的循环实现
```

### 陷阱9：让生成者自己判定产出（v4 新增）

```python
# ❌ 错误：Generator 调用 self.verify() 评判自己刚写的代码
result = await self._write_code(task)
if await self.verify(result):   # 同一 Agent 既写又判
    return result
# Agent 天然是过于乐观的自我评估者，会"觉得没问题"

# ✅ 正确：产出交给独立 Verifier / Evaluator（见 references/09-multi-agent.md）
report = await self.verifier.verify(artifact=result, context={...})
if not report.passed:
    # 把结构化 sensor 注入下一轮，让 Generator 重新行动
    self.state.messages = [
        *self.state.messages,
        {"role": "user", "content": self._format_verification_sensor(report)},
    ]
    continue
```

**修正**：计算型检查（compile / lint / type / test）天然是独立判断，优先使用；推断型评审必须交由独立 Evaluator 子 agent，禁止 `self.verify()`。这也呼应 Martin Fowler 的 sensors 模型——传感器是外部的客观反馈，不是 Agent 对自己的主观打分。

---

## 下一步

完成 Phase 4 后，进入 **Phase 5: 上下文管理**（参考 `references/05-phase-context.md`），实现四级压缩管道来确保上下文不会被耗尽。注意：双层循环场景下，Outer Loop 和 Inner Loop 的上下文应独立管理。