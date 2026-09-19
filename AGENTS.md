# AGENTS.md

> 本文件是**给 AI coding Agent 的仓库级持久指令**（"给 Agent 的 README"）。
> 与之互补的两类文件：**Skill 教怎么做**（`references/`），**MCP / 原生工具提供能力**。
> 三者层次：skill 教怎么做 · 工具提供能力 · 本文件给持久约束。

## 仓库是什么

`agent-harness-engineer` 是一个 **Agent Skill**（遵循 Agent Skills 开放标准），用于指导 AI coding 工具构建**生产级 Agent 系统**。

- 它本身不是可运行的 Agent 代码，而是一套**提示词工程产物 + 参考资料**
- 使用者是 AI coding 工具（Claude Code、Codex、Cursor、Gemini CLI 等）
- 当前版本 **v4**

## 铁律（改动本仓库前必读）

1. **禁止在 `references/` 里写完整可运行实现。**
   只能是"抽象接口 / 类骨架 + `raise NotImplementedError("AI: <构建提示>")` + AI 构建提示"。
   理由：本 Skill 明令 AI 必须自己设计而非复制，reference 里出现完整实现等于自拆台。

2. **禁止在 `templates/` 和 `examples/` 里写可直接运行的完整实现。**
   必须是"真实方法签名 + TODO + AI 构建提示"。方法签名与类型注解**必须保留**，不要注释掉。

3. **一切新增/修改都要过三级规模**（Minimal / Professional / Enterprise），并以三档差异表呈现。

4. **每个新章节开头写"何时读本章"**，这是渐进式披露的一部分。

5. **文档引用保持稳定。** 新增/更名/删除文件时，必须同步更新：
   `SKILL.md` 的快速导航与加载路由表、`README.md`、`README_ZH.md`、`references/` 内部互引。

6. **单一事实源。** 同一事实（如沙箱启动耗时、错误分类、安全层编号、Budget 结构）只允许有一处权威定义，
   其余位置必须引用。已知事实源：
   | 事实 | 权威位置 |
   |------|---------|
   | 安全层编号（Layer1-6）与 Budget 预算模型 | `references/06-phase-permissions.md` |
   | 错误分类 ErrorKind 五类与重试语义 | `references/08-core-concepts.md` |
   | 沙箱性能数据与选项 | `references/12-sandbox-advanced.md` |
   | 压缩管道与阈值 | `references/05-phase-context.md` |
   | 评测指标与门禁阈值 | `references/15-evaluation.md` |

## 目录结构

```
SKILL.md                     中枢：快速导航、加载路由表、需求确认、十一大设计哲学
AGENTS.md                    本文件
CHANGELOG.md                 版本变更记录
references/                  15 个参考文档（01-15），是 Skill 的主体内容
  01-phase-init.md           项目初始化（含 AGENTS.md 生成规范、skills 三级加载契约）
  02-phase-llm.md            LLM 抽象层（含 ModelRouter）
  03-phase-tools.md          工具系统（少而精 + CodeExecution + tool search）
  04-phase-agent-loop.md     Agent 核心循环（8 个 continue 站点 + Verifier 契约）
  05-phase-context.md        上下文管理（Mask→Snip→Collapse→Autocompact + 压缩台账）
  06-phase-permissions.md    权限安全（6 层纵深防御 + 预算控制）
  07-phase-production.md     生产化（确定性门禁清单）
  08-core-concepts.md        核心概念速查（ErrorKind、十一条设计哲学）
  09-multi-agent.md          多智能体（含独立 Evaluator）
  10-mcp-integration.md      MCP / A2A / AG-UI
  11-technology-stack.md     技术栈分级推荐
  12-sandbox-advanced.md     沙箱深度设计（跨平台矩阵、红队自检）
  13-long-running-session.md 长时运行与跨会话交接
  14-observability.md        可观测性（质量指标、生产回流）
  15-evaluation.md           Phase 8 评测与回归门禁
templates/                   三档**规模脚手架**（骨架，作为生成起点）
  minimal/ professional/ enterprise/
examples/                    完整架构的**教学参考**（已骨架化，禁止直接复制）
evals/                       结构化评测套件（scenarios / graders / baseline）
```

## 改动后的自检清单

- [ ] 未在 `references/` `templates/` `examples/` 中引入完整可运行实现
- [ ] 新增章节有"何时读本章"与三档差异表
- [ ] 未引入与既有事实源重复的第二套定义
- [ ] `SKILL.md` 导航 / 路由表 / 版本号已同步
- [ ] `README.md` 与 `README_ZH.md` 的描述未失效
- [ ] `CHANGELOG.md` 已追加条目
- [ ] 未引入已弃用的第三方库（参见 `references/11-technology-stack.md` 的维护状态判据）
- [ ] 涉及安全默认值的改动，方向均偏保守（deny 优于 allow，阻断优于放行）

## 本仓库不适用的事

- 不要在根目录下新增可运行的 Agent 源码，本仓库不产出运行时代码
- 不要把完整的第三方库文档搬进来，用引用链接
- 不要同时维护两份语言不一致的说明而不同步更新
