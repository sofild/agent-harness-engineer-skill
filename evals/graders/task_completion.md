# Grader Rubric: 任务完成层（Task Completion）

> 本 rubric 供 LLM-as-judge 在 `assert_final.terminal_state` 之外的**语义维度**打分使用。
> 所有可机检项（状态枚举、成本、循环）已由代码判定，本 rubric 只覆盖需语义理解的维度。
> 使用前提：judge 已通过 §5 校准（一致率 ≥ 85%，含 pairwise 换位测试）。

## 维度与评分尺度

| 维度 | 尺度 | 判定要点 |
|---|---|---|
| 端到端成功 | resolved / partial / failed / needs_human | 是否真正达成用户意图，而非仅「跑了流程」 |
| 部分完成质量 | 0–1 | partial 时对可交付中间态的完整性评估 |
| 人工介入必要性 | 是/否 | 是否本可由 Agent 独立完成却推给人类 |

## 关键陷阱（judge 易错点）

1. **把「流程跑完」当「任务完成」**：订单分诊 Agent 报告「问题已解决」但退款 API 实际失败——必须核对 `must_contain` / `must_not_contain`，不得轻信终态文本。
2. **被话术流畅误导**：选错工具但解释漂亮，仍判 failed。
3. **忽略跨轮一致性**：第4轮与第1轮矛盾的，即便单轮通顺也不算 resolved。

## 输出格式（建议）

```yaml
judge_verdict:
  dimension: task_completion
  score: resolved        # resolved | partial | failed | needs_human
  rationale: "<一句依据>"
  confidence: 0.9
```
