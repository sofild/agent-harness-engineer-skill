# evals/ 评测套件（Phase 8）

> 本目录是 Agent Harness Engineer v4 的评测与回归门禁数据。配套方法论见 `references/15-evaluation.md`。
> 旧版 `evals.json`（25 条纯自然语言用例，无断言、无评分器）已废弃并删除。

## 目录结构

```
evals/
├── scenarios/            # 结构化评测用例（可机检断言）
│   ├── scale-build.yaml      # 构建规模判定（7 条）
│   ├── tech-stack.yaml       # 技术栈选型（5 条）
│   ├── anti-copy.yaml        # 反拷贝（4 条，特色类别）
│   ├── sandbox.yaml          # 沙箱隔离（3 条）
│   ├── migration.yaml        # 升级迁移（2 条，已修正 phases 越界）
│   ├── integration.yaml      # 集成（4 条，已修正 phases 越界）
│   └── evaluation.yaml       # 评测相关新增（10 条，补齐四类矩阵）
├── graders/              # LLM-as-judge 评分 rubric（语义维度）
│   ├── task_completion.md
│   ├── trajectory_quality.md
│   ├── safety_compliance.md
│   └── anti_copy.md
├── baseline.json         # 基线指标（CI 门禁相对基线判定波动）
└── README.md             # 本文件
```

**用例总数：35 条**（覆盖 scale-build / tech-stack / anti-copy / sandbox / migration / integration / evaluation 七类，含 happy / edge / adversarial / off-topic 四类矩阵）。

## 用例字段定义

每条用例（YAML mapping）含：

| 字段 | 含义 |
|---|---|
| `id` | 唯一编号 |
| `prompt` | 输入 prompt |
| `scale` | minimal / professional / enterprise |
| `category` | 七类之一 |
| `matrix` | happy / edge / adversarial / off-topic |
| `source` | 脱敏生产日志 / 历史故障 / 团队设想 / 对抗样本（优先级递减） |
| `weight` | 按失败代价加权（happy=1，edge=2–3，adversarial=5） |
| `phases` | 关联构建阶段（1–7）或评测阶段（8）；**无越界编号** |
| `assert_trace` | 轨迹断言：required_tools / forbidden_tools / order_sensitive / max_steps / max_loops / no_silent_error_skip / recovery_required |
| `assert_final` | 终态断言：terminal_state / must_contain / must_not_contain / policy_compliance / cost / anti_copy |

## 如何跑（Runner 接口骨架）

> 铁律：以下为抽象接口与 AI 构建提示，**不得作为完整实现**。AI 须自行设计 Runner。

```python
class EvalRunner:
    def load_suite(self, path: str) -> list[Scenario]:
        """AI: 读取 scenarios/*.yaml，解析为 Scenario 对象列表。"""
        raise NotImplementedError("AI: 实现 YAML 加载与字段校验")

    def run_one(self, scenario: Scenario, agent) -> Trace:
        """AI: 把 scenario.prompt 喂给被测 Agent，采集完整 trace（工具调用序列+终态）。"""
        raise NotImplementedError("AI: 实现 trace 采集（联动 references/14-observability.md）")

    def assert_trace(self, trace: Trace, spec: dict) -> list[Violation]:
        """AI: 代码判定 required_tools/forbidden_tools/order/max_steps/max_loops。"""
        raise NotImplementedError("AI: 实现确定性断言引擎")

    def assert_final(self, trace: Trace, spec: dict) -> list[Violation]:
        """AI: 代码判定 terminal_state/cost/anti_copy；语义项转交 judge。"""
        raise NotImplementedError("AI: 实现终态断言 + judge 分发")

    def gate(self, results: list[Result], baseline: dict) -> Gate:
        """AI: 套用 references/15-evaluation.md §7 阈值，返回 pass/fail。"""
        raise NotImplementedError("AI: 实现门禁聚合（安全类=0 硬门禁）")
```

**最小运行流程**：`load_suite` → 逐条 `run_one` 采 trace → `assert_trace` + `assert_final` 机检 → 语义维度交 `graders/*.md` 的 judge（须先校准 ≥85%）→ `gate` 对比 `baseline.json`。

## 门禁阈值

默认阈值见 `references/15-evaluation.md §7`（成功率 ≥90%、策略违规/泄漏/越界 =0、成本波动 ≤±15%、`pass^5_happy ≥80%`、`pass^1_adversarial =100%`）。

## 生产回流

生产异步采样 1%–5% → 校准 judge 异步评分 → 新失败模式沉淀为 `scenarios/*.yaml` 新用例（带断言），进入 golden set；golden set 第一年增长 10%–30% 为健康指标。
