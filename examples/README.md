# examples/ — 完整架构教学参考（**禁止直接复制**）

> ⚠️ **这不是脚手架。**
> 想生成项目请用 [`templates/minimal/`](../templates/minimal/)、[`templates/professional/`](../templates/professional/)、[`templates/enterprise/`](../templates/enterprise/)。
> 本目录的作用是：**让你看清一套完整 Agent 架构由哪些模块组成、它们怎么接线**，然后回去自己设计实现。

## 为什么它被单独拎出来

v3 时代这里叫 `templates/project-scaffold/`，里面是一套**零 TODO 的完整可运行实现**。那是个错误：

1. 它和本项目最核心的规则互斥 —— 本项目明令 *AI 必须自己设计而非复制*，却在自家目录里放了一整套可直接抄走的实现；
2. 那些实现缺少安全约束（最典型：`read_file` 直接 `open(path)`，没有任何路径白名单校验），会被当作"正确范式"学走 —— 等于亲手教出一个可以读取 `~/.ssh/id_rsa` 的 Agent。

v4 的处理：**把它移出 `templates/`，改名 `examples/`，并全面骨架化**，同时把安全约束写成显式契约。

## 你现在在这里能看到什么

- **真实的方法签名与类型注解**（不去注释签名，签名就是契约）
- **方法体一律是 `raise NotImplementedError("AI: <构建提示>")`**
- **构建提示里写明要做什么、有哪些陷阱、必须满足什么约束**
- 配置文件（`config/settings.yaml`、`requirements.txt` 等）保持原样 —— 它们是配置，不是实现

## 两个 Python / Node.js 目录的关系

`python/` 与 `nodejs/` 是同一套架构的两种语言镜像，结构一致：

```
src/agent/         核心循环、会话（WAL）、上下文压缩、记忆
src/llm/           客户端抽象、工厂、供应商适配、ModelRouter
src/tools/         工具注册表、文件工具、网络工具
src/permissions/   权限模型、Hook 系统、沙箱
src/utils/         结构化日志、错误分类
config/            YAML 配置、Agent 角色、Hook 脚本
tests/             单元与集成测试骨架
```

## 阅读时的三条建议

1. **先看 `src/agent/core.py`**，它是整套系统的骨架 pin：主循环、8 个 continue 站点、安全护栏、预算检查点都在这里接线。
2. **安全相关的文件请配合 `references/06-phase-permissions.md` 与 `references/12-sandbox-advanced.md` 一起看** —— 本目录里出现的安全约束是为了提醒，权威定义在 reference 里。
3. **看到 `raise NotImplementedError` 不要觉得是偷懒**，那才是本项目的正解：把设计权交还给 AI / 开发者。

## 已知待办

- 部分早期文件仍采用"注释掉的签名 + `pass`"的旧骨架写法，尚未统一为最新标准
  （真实签名 + `raise NotImplementedError("AI: ...")`）。见到这类文件按同样标准处理即可。
- `SafetyGuardLoop` 的权威定义在 `references/06-phase-permissions.md`，本目录只保留差异说明，不再复制一份。
