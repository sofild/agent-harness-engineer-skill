# Grader Rubric: 轨迹质量层（Trajectory Quality）

> 工具选择准确率 / 步数 / 循环已由 `assert_trace` 代码判定；本 rubric 覆盖需语义判断的维度。

## 维度与评分尺度

| 维度 | 尺度 | 判定要点 |
|---|---|---|
| 工具选择恰当性 | 0–1 | 每步工具是否「该场景下最优」（允许等价替代） |
| 错误恢复质量 | 0–1 | 工具报错后是重试/升级/上报，还是无视后幻觉（失败模式③） |
| 跨轮一致性 | 0–1 | 多轮对话中事实/决策是否前后一致（失败模式④） |

## 关键陷阱（judge 易错点）

1. **把「重试一次就成功」当高质量恢复**：若恢复路径不稳定（同一错误反复出现），质量分应打折，并触发 `pass^k` 复测。
2. **忽略循环**：`assert_trace.max_loops` 已机检死循环；judge 额外关注「伪循环」（不同工具但等效空转）。
3. **步数不是越少越好**：必要的中间验证步是质量信号；judge 评估的是「是否有冗余/绕路」，不是纯步数。

## 输出格式（建议）

```yaml
judge_verdict:
  dimension: trajectory_quality
  tool_selection: 0.95
  error_recovery: 0.85
  consistency: 0.90
  rationale: "<一句依据>"
```
