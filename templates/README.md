# Agent Harness Engineer — 项目模板

## templates/ 与 examples/ 的区别（先看这个）

本仓库有两个容易被混淆的目录，它们**都不是拿来复制的**：

| 目录 | 定位 | 什么时候用 |
|------|------|-----------|
| `templates/minimal/`<br>`templates/professional/`<br>`templates/enterprise/` | **规模脚手架** —— 按三档规模裁剪的项目起始骨架 | 开始建项目时选一档，作为生成起点 |
| [`examples/`](../examples/) | **教学参考** —— 完整架构长什么样的骨架化对照图 | 想理解"各模块如何接线"时去读，**不要**当脚手架 |

> 关于 `project-scaffold`：v3 里的 `templates/project-scaffold/` 是一套零 TODO 的完整实现，
> 与本项目的禁止复制规则直接冲突。v4 已将它移出 `templates/`、改名 `examples/` 并全面骨架化。

---

## 核心规则：这是骨架，不是答案

每个模板文件都遵循**同一条铁律**：

```
真实方法签名 + 类型注解  +  raise NotImplementedError("AI: <构建提示>")
```

**AI coding 工具必须根据用户的需求、规模和技术栈自行设计实现，不得直接复制模板代码。**

为什么：
- 抄来的实现永远停留在"最小可用"，无法响应你的复杂度要求
- 抄来的实现常常带着安全缺陷（`read_file` 不带路径白名单是最典型的一个）
- 本 Skill 的全部价值在于"引导设计"，而不在于"提供代码"

---

## 三档规模模板

### minimal — 极简快速原型
适合：快速验证想法、单文件 Agent、学习目的

- 源文件：`main.py` + `agent.py`
- 无工具系统、无权限管理；文件路径扫描需求极少
- 单轮 LLM 调用封装
- 工具：**1-3 个强工具**（v4：不再是 3-5 个）
- 上下文压缩：仅 Mask（工具结果遮蔽）
- 评测：5-10 条手工冒烟场景
- ~300-500 行总代码量

### professional — 生产就绪单体
适合：真实项目、团队协作、需要工具系统的 Agent

- 完整模块分层：`agent/` `llm/` `tools/` `permissions/` `utils/`
- **8 个 continue 站点**的主循环（v4 新增 Verification Failure）
- 抽象接口：LLMClient、ToolRegistry、Permission、Budget
- 确定性门禁：compile → lint → type → unit → integration
- 工具：**5-8 个 + 可选代码执行模式**
- 预算：Budget + 两级降级
- 评测：30-100 条 + CI 回归门禁
- ~2000-4000 行总代码量

### enterprise — 分布式平台
适合：高并发、多租户、可观测性与合规要求高的平台

- Professional 全部能力 + 分布式特性
- Redis 会话、PostgreSQL 持久化
- OpenTelemetry 追踪、Prometheus 指标
- Docker Compose 部署、FastAPI 服务
- 多 Agent 编排（含独立 Evaluator）
- 工具：工具目录 + `tool search` + 沙箱代码执行
- 长时运行：Initializer / Coding 双角色 + feature list + 跨会话 handoff
- 评测：100-1000 条 + 生产采样 + 趋势告警
- ~6000-10000+ 行总代码量

---

## 使用方式

根据用户描述自动选择规模，AI 会按骨架中的构建提示填充实现：

```
用户: "帮我创建一个简单的 Python Agent"
→ minimal 模板

用户: "搭建生产级 Agent, 需要工具系统和权限控制"
→ professional 模板

用户: "构建企业级 Agent 平台, 支持多租户和可观测性"
→ enterprise 模板
```

不确定时默认 **Professional**，并向用户说明理由（见 `SKILL.md` 的默认值策略）。

---

## 模板自检清单（新增/修改模板时必须满足）

- [ ] **anti-copy**：无任何可直接运行的完整实现，方法体均为 `raise NotImplementedError("AI: <构建提示>")`
- [ ] **真实签名**：方法签名与类型注解保留，没有被注释掉
- [ ] **干净 lint**：无未使用的 import、无未定义引用
- [ ] **构建提示具体**：说清要做什么、有哪些陷阱、要满足哪些约束，而不是一句"实现它"
- [ ] **安全约束显式**：涉及文件读写、命令执行、网络访问的地方，必须在注释里写死安全要求
      （路径白名单、最小权限、超时默认 deny、输出不超过预算）
- [ ] **三档一致**：同一能力在三档模板中的差异符合 `SKILL.md` 的规模表
- [ ] **v4 同步**：错误路径声明了 ErrorKind 与幂等性；continue 站点按 8 个理解
- [ ] **单一事实源**：重复出现的类（如 `SafetyGuardLoop`）只保留一处权威定义，其余引用
