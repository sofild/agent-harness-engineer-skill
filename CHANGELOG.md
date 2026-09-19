# CHANGELOG

本项目遵循 [Semantic Versioning](https://semver.org/) 风格的版本约定。所有破坏性变更都会在正文中标出迁移方式。

---

## v4.0.0 — 2026-09-19

v4 是一轮**结构性升级**：补齐四大缺口（评测、确定性验证、预算、长时运行），修正两处方向性反了的范式（压缩管道、工具系统），同步 2026 开放标准。

### 破坏性变更（Breaking Changes）

| 变更 | v3 | v4 | 迁移方式 |
|------|----|----|---------|
| `13` 文件更名 | `references/13-session-design.md` | `references/13-long-running-session.md` | 更新所有引用；原 WAL/checkpoint 内容完整保留为"进程内层" |
| `project-scaffold` 移除 | `templates/project-scaffold/`（完整可运行实现） | 移至仓库根 `examples/` 并**全面骨架化** | 不再作为脚手架使用；仅作教学参考，禁止直接复制 |
| 压缩管道顺序 | Snip → Microcompact → Collapse → Autocompact | **Mask（遮蔽）→ Snip → Collapse → Autocompact** | 遮蔽提为首选且有旋律之最优先；原 Level1/Level2 顺序对调 |
| 压缩触发阈值 | 85% | **60-70%（默认 65%）** | 已生成系统的阈值配置需下调 |
| 工具数量建议 | 3-5 / 10-20 / 50+ | **1-3 / 5-8 / 工具目录 + tool search** | 现有工具集按"先减后加"路径收敛 |
| Hook 超时行为 | 超时放行（allow） | **超时 DENY**（或升级人工审批） | 依赖放行兜底的场景需改为显式授权 |
| 断点超时语义 | 统一"超时自动放行" | 区分**审批类**（可放行）/ **阻断类**（保持阻断并告警） | 检查现有 BLOCK 级规则配置 |
| continue 站点数量 | 7 个 | **8 个**（新增 Verification Failure） | 状态机实现需补第 8 个分支 |
| MCP 远程传输 | HTTP+SSE | **Streamable HTTP**（SSE 降级为遗留兼容） | 新建集成默认走 Streamable HTTP |

### 新增

**A1 · Phase 8 评测与回归门禁**（新增 `references/15-evaluation.md`）
- 三层指标体系：任务完成 / 轨迹质量 / 安全合规
- 四类用例矩阵（happy / edge / adversarial / off-topic），按失败代价加权
- `assert_trace` / `assert_final` 场景规格 schema
- LLM-as-judge 校准流程：50 条人工标注、一致率 <85% 不得进门禁、pairwise 换位测试
- `pass^k` 可靠性指标（替代 `pass@k`）
- CI 门禁默认阈值：成功率 ≥90%、安全类违规 =0、成本相对基线 ≤±15%、pass^5 ≥80%
- 生产回流闭环：1-5% 异步采样、失败入 golden set
- `evals/` 重构为结构化套件（scenarios 35 条 / graders / baseline）

**A2 · 确定性验证回路**（`04`、`07`）
- CONTINUE-SITE-8：Verification Failure（结构化失败输出作为 sensor 注入下一轮，连续 3 次升级 replan/人工）
- Verifier 契约 `verify(artifact, context) -> VerificationReport`，区分计算型 / 推断型
- 硬约束：生成者不得作为自己产出的最终评判者
- `07` 新增确定性门禁清单，输出必须机器可解析

**A3 · 统一错误分类与可重试语义**（`08`）
- `ErrorKind` 五类：`retryable` / `fatal` / `degrade` / `replan` / `human_required`
- 退避默认值（base 1s、factor 2、max 30s、全抖动、max_attempts 5）与幂等性约定
- 散文式错误 → ErrorKind 映射表

**A4 · 预算与成本控制**（`06`、`02`）
- `Budget` / `BudgetPolicy` 结构与单位
- 四级降级链：warn → 切便宜模型 → 削工具与上下文 → 暂停请求人工 → 终止并交接
- `02` 新增 `ModelRouter` 接口（按步骤类型路由 cheap/strong，决策可审计）

**A5 · 长时运行与跨会话交接**（`13` 重构）
- 三件持久化产物 schema：feature_list.json（含 `passes`）、progress 文件、init.sh
- Initializer / Coding 双角色模型
- 五步会话初始化仪式（harness 强制）+ Bootstrap Contract 四问
- test ratchet 约束、checkpoint LLM 元数据（model id/version/temperature/seed）、WAL 滚动归档

**B1 · 压缩管道重构**（`05`）
- 除上述顺序与阈值外：新增 `CompactionLedger` 压缩台账、schema 化摘要（强制含"已排除的方案及原因"）、外部记忆层（scratchpad + 路径校验）、服务端压缩/context editing 对接、head 逐字节不变硬约束

**B2 · 工具系统反转**（`03`、`08`）
- 工具设计三原则（少而精 / 为 Agent 设计 / 数量与准确率反比）
- `CodeExecution` 模式（含适用与不适用边界）
- tool search 延迟加载（对 prompt cache 零影响）
- 工具输出后处理钩子

**B3 · 可观测性质量维度**（`14`）
- 8 个质量指标（tool_selection_accuracy、steps_per_task、loop_detection_count、error_recovery_rate、policy_violation_rate、injection_resistance、escalation_rate、cost_per_task）
- 生产采样回流与相对基线趋势告警
- 日志脱敏白名单

**C1 · Agent Skills 渐进式披露 + AGENTS.md**（`01`、`08`、仓库根 `AGENTS.md`）
- skills 三级加载契约（索引 → 命中 → 资源）+ SkillLoader 抽象接口与 token 预算
- AGENTS.md / CLAUDE.md 生成规范
- 供应链安全提示：持有 skill ≠ 获得工具授权

**C2 · 独立 Evaluator 与对抗式验证**（`09`）
- Evaluator 一等拓扑 + 四条构造约束
- 对抗式验证变体与适用边界
- 各拓扑 token 倍率与缺陷成本门槛

**C3 · 协议层更新**（`10`）
- Streamable HTTP 为远程默认、MCP 治理现状与 spec 基线、tool search
- A2A / AG-UI 定位与选型
- MCP 供应链与命令注入风险条目

**D3 · 生态刷新**（`12`、`11`、`SKILL.md`）
- `12`：跨平台矩阵、microsandbox / Docker Sandboxes / WASM、红队逃逸自检清单、三档资源限额
- `11`：移除弃用项（`vm2` 等）、新增评测/追踪/路由/沙箱四个维度、选型维护状态判据
- `SKILL.md`：description 补齐 2026 触发词、新增 **reference 加载路由表**

### 修复（D1 · 一致性）

- `06` 的两套互斥安全层模型收敛为一套 Layer1-6，原 v4 附录改为"6 层模型在 v4 技术下的映射表"
- 沙箱性能数据收敛到单一事实源 `12`，`06` 改为引用
- 版本号全库统一为 v4
- `evals` 中引用不存在的 Phase 编号已修正（原 `[9]`）
- 两份 README 关于模板体系的描述已统一（templates=规模脚手架，examples=教学参考）

---

## v3.0.0

- 引入三级构建规模（Minimal / Professional / Enterprise）
- 引入代码生成禁止复制策略
- 引入技术栈分级推荐
- 引入抽象接口引导模式：reference 中的代码改为"抽象接口/骨架 + AI 引导提示"

## v2.0.0

- 提供分阶段构建指南，每阶段含理论指导、实践步骤、检查清单、常见问题

## v1.0.0

- 提供理论文档与最小示例
