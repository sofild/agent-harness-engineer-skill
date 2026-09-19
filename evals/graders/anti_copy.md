# Grader Rubric: 反拷贝（Anti-Copy，本 Skill 特色）

> 对应 `assert_final.anti_copy.no_verbatim_reference`。本 rubric 指导「相似度机检 + judge 复核」两阶段判定。

## 判定流程

```
1. 代码阶段：将输出代码与 references/ 同主题骨架做逐字/近字相似度比对
   - 相似度 > 阈值（如 0.85）→ 直接判失败，无需 judge
2. judge 阶段（仅相似度处于灰区时）：语义判断
   - 是否保留了架构约束（Session WAL / 四级压缩 / 6层防御）但实现路径不同
   - 变量命名、错误处理、扩展点是否体现「自行设计」
```

## 关键陷阱（judge 易错点）

1. **把「结构相同」当「复制」**：架构约束相同是允许的（Skill 要求保留设计原则），复制指「逐字实现」而非「同构设计」。
2. **忽略注释标记**：输出中出现 `directly copied from reference` / `adapted from template` 等标记，直接判失败。
3. **混淆模板与参考**：templates/ 是骨架 + TODO，references/ 是抽象接口；两者都禁止逐字复制。

## 输出格式（建议）

```yaml
judge_verdict:
  dimension: anti_copy
  similarity_score: 0.42
  verbatim_copy: false
  rationale: "<一句依据>"
```
