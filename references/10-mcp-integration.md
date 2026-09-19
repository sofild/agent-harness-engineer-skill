# MCP 集成

## 协议概述

MCP（Model Context Protocol）定义了 AI 模型与外部工具、数据源之间的标准化接口。在 Harness 架构中，MCP 是 Agent 扩展能力的主要入口——通过 MCP Server 注册的工具和资源，Agent 可以获得超出内置工具的领域特定能力。

**核心概念：**
- **Server**：提供工具和数据的服务端（独立进程或远程服务）
- **Client**：使用工具和数据的客户端（即 Agent Harness）
- **Tool**：Agent 可以调用的功能（参数化操作）
- **Resource**：Agent 可以访问的数据（文件、数据库、API 结果等）
- **Transport**：Client 与 Server 之间的通信管道

---

## 传输协议选择指南（stdio 本地默认 / Streamable HTTP 远程默认）

每种传输协议有不同的适用边界。选错协议会导致性能问题或架构耦合：

### stdio（标准输入输出）

**工作原理**：Client 通过子进程的 stdin/stdout 与 MCP Server 通信。Server 作为 Client 的子进程启动。

**何时选择：**
- 本地工具（文件系统操作、本地数据库查询、代码分析工具）
- 零配置要求——不需要网络、不需要认证
- 天然进程隔离：Server 崩溃不影响 Client

**何时避免：**
- 需要跨机器访问（stdio 绑死在同一台机器）
- Server 需要保持长时间运行的状态（随 Client 进程生命同期）
- 需要负载均衡（一个 Server 只能服务一个 Client）

**启动参数模式**：通过命令 + 参数指定 Server 可执行文件路径，环境变量注入配置。

### Streamable HTTP（远程默认）

**工作原理**：基于单一 HTTP 端点（POST 请求 + 可选的可恢复 SSE 流）承载 MCP 会话。Client 通过普通 HTTPS 与 Server 通信，Server 可借助标准反向代理、负载均衡器与 CDN 横向扩展。这是 **2026 年远程 MCP 的推荐默认传输**，已取代 HTTP+SSE。

**何时选择：**
- 远程服务（跨网络 / 跨数据中心）—— 远程场景的**默认首选**
- 需要负载均衡（多个 Client 共享同一个 Server 集群，无状态端点易于水平扩展）
- Server 需要独立部署和运维（不随 Client 生命周期绑定）
- 需要 Server 主动推送事件（通过同一会话内的可恢复 SSE 流）
- 与现有 Web 基础设施（OAuth、网关、WAF）无缝对接

**何时避免：**
- 本地场景：引入不必要的网络栈复杂度和延迟，此时应优先 stdio
- 需要真正的全双工双向消息（Client 也要在无请求时主动推给 Server）—— 选 WebSocket

**关键设计要点**：单个 POST 端点接收 JSON-RPC 请求；Server 通过 `text/event-stream` 在同一会话回传流式响应；会话状态经 `Mcp-Session-Id` 头关联，断线后可恢复，无需长久存活的 SSE 连接。

### HTTP + SSE（Server-Sent Events）⚠ 遗留兼容

> **状态：已由 Streamable HTTP 取代，仅保留用于遗留 Server 兼容。** 新项目一律使用 Streamable HTTP；仅在对接尚未升级的老 Server 时临时启用。

**工作原理**：HTTP 承载请求，SSE 长连接承载 Server 到 Client 的推送（如资源变更通知）。曾是远程 MCP 的标准选择，现已由 Streamable HTTP 接替。

**何时选择（仅遗留）：**
- 对接尚未支持 Streamable HTTP 的老旧 MCP Server
- 无法升级、且强依赖"独立 SSE 长连接推送"的既有部署

**何时避免：**
- 所有新开发：开销更高（需维护一条常驻 SSE 连接），且缺乏 Streamable HTTP 的会话可恢复性与横向扩展能力
- 对延迟极度敏感（~1ms 级别）：HTTP 的 TCP 握手和 Header 开销不可忽略

### WebSocket

**工作原理**：全双工持久连接，Client 和 Server 可以在任意时刻主动发送消息。

**何时选择：**
- 实时交互场景（如协作编辑、实时监控面板）
- 需要双向高频率推送（Client 和 Server 都需要主动发送）
- SSE 的"Server → Client 单向流"不够用

**何时避免：**
- 简单的请求-响应模式：WebSocket 的连接管理开销超过 HTTP
- Server 不需要主动推送的任何场景

### gRPC

**工作原理**：基于 HTTP/2 + Protocol Buffers 的高性能 RPC 框架，支持双向流。

**何时选择：**
- 高性能微服务（需要毫秒级延迟和protobuf 零拷贝序列化）
- 已有 gRPC 基础设施的组织（服务网格、统一的 proto 定义）
- 需要类型安全的接口契约（proto 文件即契约）

**何时避免：**
- 协议要求简单的场景：gRPC 需要 proto 编译步骤和 stubs 生成，增加构建复杂度
- 浏览器环境：gRPC-web 可用但功能受限
- 对外提供给第三方：REST API 的通用性远高于 gRPC

### Local（同进程函数调用）

**工作原理**：工具直接作为内存中的函数注册，无序列化、无进程边界。

**何时选择：**
- 极低延迟需求（函数调用 < 1μs）
- 工具逻辑简单且可信（不需要安全隔离）
- 原型阶段（快速集成，跳过 MCP Server 开发）

**何时避免：**
- 需要安全隔离：同进程内无隔离，工具崩溃可能导致 Agent 进程崩溃
- 需要语言无关性：Local 模式绑死 Agent 实现语言
- 工具逻辑复杂或需要独立资源管理

### 协议选型决策树

```
需要跨机器访问？
  ├── 是 → 需要实时双向通信？
  │         ├── 是 → WebSocket
  │         └── 否 → 需要 protobuf 契约？
  │                   ├── 是 → gRPC
  │                   └── 否 → Streamable HTTP（远程默认；HTTP+SSE 仅遗留兼容）
  └── 否 → 需要安全隔离？
            ├── 是 → stdio（本地默认，子进程隔离）
            └── 否 → Local（同进程函数调用）
```

---

## MCP 治理现状与协议基线

**何时读本节**：当你要确认"我们用的 MCP 是哪个版本、归谁管、能力怎么协商、工具太多怎么检索"这些协议级事实时。

### 治理现状

- **归属**：MCP 于 **2025-12-09** 捐赠给 **Linux Foundation 的 Agentic AI Foundation**（与 Agent Skills 同一治理主体；Agent Skills 规范见 `references/01-phase-init.md`）。
- **意义**：协议不再由单一厂商控制，spec 演进经开放治理流程，跨厂商互操作性更有保障。
- **实践提示**：选型时优先支持"已捐给基金会"的标准能力，避免锁定某厂商私有扩展。

### spec 版本基线

- 以 `initialize` 握手中协商的 `protocolVersion` 为基线，Client 与 Server 取双方支持的交集。
- Harness 应记录实际协商到的版本号到 Session 日志，便于事后审计"当时用的是哪版协议"。
- **铁律**：不假设 Server 支持最新私有字段；任何可选能力使用前必须先经能力协商确认。

### 能力协商（capabilities）

```
initialize 握手（抽象，非可运行）：
  Client ──→ initialize(protocolVersion, capabilities{tools, resources, prompts, ...})
  Server ──→ InitializeResult(protocolVersion, capabilities{...}, serverInfo)
  双方取 capabilities 交集 → 仅启用协商通过的能力
  例：Server 未声明 resources → Client 不调用 resources/read
```

### tool search（工具检索，2026 关注点）

- **问题**：把成百上千个 MCP 工具的完整 schema 全部注入 system prompt，会撑爆上下文并抬高 token 成本（详见 `references/08-core-concepts.md` 的 Prompt Cache 稳定性机制）。
- **方向**：从"全量注入"转向"按需检索"——Client 先拿到工具索引（name + description），按当前任务语义检索相关工具，命中后才拉取完整 schema 注入。
- **落地**：能力协商阶段确认 Server 是否支持工具检索接口；不支持时退化为分层注入（内置工具稳定前缀 + MCP 工具追加在缓存边界之后，见 08）。

---

## A2A / AG-UI 定位与选型

**何时读本节**：当你在"MCP 之外，还要不要接 A2A 或 AG-UI"之间犹豫时。

### 三者分工

```
┌─────────────────────────────────────────────────────────┐
│  MCP   → Agent 连「工具与数据」   (tool / resource / prompt) │
│  A2A   → Agent 连「Agent」       (跨进程智能体协作)         │
│  AG-UI → Agent 连「用户前端」     (流式 UI 事件 / 人机界面)   │
└─────────────────────────────────────────────────────────┘
```

| 协议 | 连接两端 | 解决的核心问题 | 典型场景 |
|------|----------|----------------|----------|
| **MCP** | Agent ⇄ 工具 / 数据源 | 标准化"调能力、读数据" | 文件系统、数据库、第三方 API、CI |
| **A2A** | Agent ⇄ Agent | 跨进程 / 跨组织的智能体协作与任务委派 | 多厂商 Agent 组网、长任务委派 |
| **AG-UI** | Agent ⇄ 前端（React 等） | 把 Agent 的流式输出 / 状态映射成 UI 事件 | 聊天界面、表单填答、人工介入面板 |

### 选型原则：大多系统只需"MCP + 三者之一"

**不要三个全上。** 绝大多数生产系统只需要 MCP，再叠加 A2A 或 AG-UI 中的**一个**：

- 你的 Agent 只和工具 / 数据打交道 → **仅 MCP** 足够。
- 你的 Agent 要和其他 Agent 协作（跨进程、跨团队、跨厂商）→ MCP + **A2A**。
- 你的 Agent 要驱动一个富前端界面（流式渲染、人工介入控件）→ MCP + **AG-UI**。
- 同时需要"Agent 间协作"和"前端驱动"的极少数场景，才考虑三者并用——且应先确认前两者各自带来的复杂度是否必要。

### 与 `references/09-multi-agent.md` 的对接

09 的两种跨进程拓扑走 A2A 最自然：

```
Coordinator 模式（中心化）：
  Coordinator Agent ──A2A──> Worker Agent（独立进程 / 独立地址）
  任务委派、结果回收走 A2A 的 task/message 协议，而非同进程函数调用

Swarm 模式（去中心化）：
  多个 Peer Agent 经 A2A 消息总线对等通信（TaskProposal / ResultShare / ConsensusVote）
  09 的 MessageBus 抽象可直接映射为 A2A 的 transport
```

- **进程内多 Agent**（09 的 Minimal / Professional 同进程子 Agent）：**不需要 A2A**，直接函数调用 / 消息总线即可，引入 A2A 是过度工程。
- **跨机器 / 跨组织多 Agent**（09 的 Enterprise Coordinator + Swarm）：用 **A2A** 承载 Agent 间通信，MCP 仍负责每个 Agent 内部的工具与数据；AG-UI 仅在需要把协作过程呈现给用户时才引入。

> 与 `references/09-multi-agent.md` 联动：A2A 是 09 拓扑循环的"跨进程 transport 实现选项"，不改变 09 的 Coordinator / Swarm 决策逻辑。

---

## MCP 供应链与命令注入风险

**何时读本节**：当你要把第三方 MCP Server 接进生产、又不想因为"它只是个工具"而放松警惕时。

### 风险事实

- **OS 命令注入暴露 API Key**：已有流行 MCP Server 被曝存在 OS 命令注入漏洞——攻击者通过构造的工具参数触发 Server 执行任意 shell 命令，进而读取并外传宿主机上的 API Key / 凭证。
- **供应链不可信**：MCP Server 本质是"以宿主凭据运行的外部代码"（与 `references/01-phase-init.md` 的 Skill 供应链风险同源：skill 也是"伪装成文档的可执行内容"）。来源不明或未锁版本的 Server 可能夹带恶意逻辑。
- **信任 ≠ 验证**：即便 Server 来自"可信厂商"，其运行时的行为仍需被验证，而非默认放行。

### 缓解分层

```
1. 隔离域（见 references/12-sandbox-advanced.md）
   └─ MCP Server 运行在独立隔离域（独立沙箱 / 微 VM），不共享 Agent 主进程命名空间
2. 最小权限
   └─ Server 仅能访问其声明的工具所需资源；网络出站默认 deny（06 的 Layer 4）
3. 凭证外置
   └─ API Key 不进入 Server 进程环境，由宿主经 06 的 credentials_request 注入
4. 默认 ask / 显式授权
   └─ 第三方 MCP 工具默认 level: ask（06 的陷阱 5；08 的 human_required 语义）
5. 供应链校验
   └─ 版本锁定 + digest 校验 + 信任门控（见 01 的 Skill 供应链安全提示）
```

### 关键认知：微 VM 隔离解决「爆炸半径」，不解决「信任与验证」

- microVM（Firecracker / microsandbox）等硬件级隔离，把**单个 Server 被攻破后的影响范围**限制在它自己的 VM 内——这是「爆炸半径」控制，非常有价值。
- 但它**不能**告诉你"这个 Server 本身是否可信、它的输出是否该被相信"。信任与验证必须由 `references/04-phase-agent-loop.md` 的**验证回路**（Verifier / CONTINUE-SITE-8）和权限模型兜底。
- 结论：隔离是必要条件，不是充分条件。MCP Server 必须"独立隔离域 + 默认 ask + 验证回路"三件套齐备。

---

## 连接管理（抽象设计）

### 连接池化

```
连接池策略：
  ├── 每个 MCP Server 地址维护一个连接池
  ├── 池大小：min 2, max 10（根据并发工具调用量动态伸缩）
  ├── 连接生命周期：
  │   ├── 创建：懒加载，首次调用时建立
  │   ├── 空闲回收：连接空闲 > 300s → 关闭（释放 Server 资源）
  │   └── 保活：每 60s 发送 ping（保持长连接存活）
  └── 连接分配：从池中取空闲连接 → 绑定到当前工具调用 → 调用完成后归还池
```

### 超时策略

```
多层超时体系：
  ├── 连接超时（Connect Timeout）：10s
  │   - 建立 TCP/进程连接的最大等待时间
  │   - 超时后重试 1 次（不同 IP / 重新启动子进程）
  ├── 请求超时（Request Timeout）：30s
  │   - 单次工具调用的最大等待时间（含 Server 处理时间）
  │   - 超时 → 中断当前调用 → 返回超时错误给 Agent
  └── 空闲超时（Idle Timeout）：300s
      - 连接池中空闲连接的最大保活时间
      - 超时 → 关闭连接，从池中移除
```

### 重连策略

```
指数退避重连：
  ├── 第 1 次失败：立即重试（可能有瞬时网络抖动）
  ├── 第 2 次失败：等待 1s 后重试
  ├── 第 3 次失败：等待 2s 后重试
  ├── 第 4 次失败：等待 4s 后重试
  ├── 第 5 次失败：等待 8s 后重试
  └── 第 6 次失败：标记 Server 不可用 → 通知 Agent → 停止重试

  不可重试的错误（立即停止）：
    ├── 认证失败（4xx）—— 重试无意义
    ├── 工具不存在（ToolNotFound）—— Server 配置问题
    └── 参数校验失败 —— 重新传同等参数仍然失败
```

---

## OAuth 集成（远程 MCP Server 认证）

远程 MCP Server 使用 OAuth 2.0 进行认证。集成流程通过抽象接口描述：

### 认证流程

```
抽象认证流程：
  Step 1 —— 发现（Discovery）
    Client 向 Server 的 /.well-known/oauth-authorization-server 获取 OAuth 元数据
    返回：authorization_endpoint, token_endpoint, scopes_supported

  Step 2 —— 授权（Authorization）
    用户通过浏览器访问 authorization_endpoint
    授权成功后，Server 通过 redirect_uri 返回 authorization_code
    (若为本地 Server，redirect_uri 可用 localhost 回调或设备码流程)

  Step 3 —— 换 Token（Token Exchange）
    Client 用 authorization_code + client_id + client_secret 向 token_endpoint 换取 access_token + refresh_token
    access_token 有效期通常 1 小时，refresh_token 有效期通常 30 天

  Step 4 —— 使用（Usage）
    每次工具调用时，Client 在 HTTP Header 中附带：
    Authorization: Bearer <access_token>
    或对于 stdio 传输，通过环境变量注入 token

  Step 5 —— 刷新（Refresh）
    access_token 过期 → Client 用 refresh_token 向 token_endpoint 静默刷新
    若 refresh_token 也过期 → 回退到 Step 1 重新授权
```

### 抽象接口

```
OAuthManager 抽象：
  ├── discover_auth_metadata(server_url) → OAuthMetadata
  │   - 从 Server 获取授权端点信息
  │   - 缓存元数据，避免每次重发现
  ├── initiate_authorization(metadata, scopes) → AuthRequest
  │   - 生成 authorization URL + PKCE code_verifier
  ├── exchange_code(auth_code, verifier) → TokenPair
  │   - 用 authorization_code 换取 access_token + refresh_token
  ├── refresh_access_token(refresh_token) → TokenPair
  │   - 用 refresh_token 刷新，返回新 token 对
  └── get_valid_token(server_id) → access_token
      - 检查 token 是否过期 → 过期则自动刷新
      - 返回始终有效的 access_token 或抛出 AuthError
```

**Token 安全存储：**
- Token 存储在操作系统的凭据管理器（macOS Keychain / Windows Credential Manager / Linux Secret Service）
- 不写入明文文件，不进入 Agent 的沙箱
- 每个 MCP Server 独立 token，不共享

---

## 资源生命周期

MCP 资源代表 Agent 可以读取的数据。资源管理遵循"发现 → 订阅 → 读取 → 取消订阅"的生命周期：

```
资源生命周期状态机：
                ┌──────────┐
     discover → │ UNKNOWN  │ ← 初始状态
                └────┬─────┘
                     │ subscribe
                     v
                ┌──────────┐
                │ SUBSCRIBED│ ← 已订阅，接收更新推送
                └────┬─────┘
                     │ read
                     v
                ┌──────────┐
                │  CACHED   │ ← 读取后结果缓存，减少重复请求
                └────┬─────┘
                     │ update notification (from Server via SSE/WebSocket)
                     v
                ┌──────────┐
                │  STALE    │ ← 缓存过期，下次 read 时重新请求
                └────┬─────┘
                     │ unsubscribe
                     v
                ┌──────────┐
                │ UNSUBSCRIBED│ ← 取消订阅，资源不可用
                └──────────┘

Transition triggers:
  discover → SUBSCRIBED: Agent 首次请求访问资源时自动订阅
  SUBSCRIBED → CACHED: read() 完成后缓存 TTL 内
  CACHED → STALE: Server 推送更新通知 或 TTL 过期
  STALE → CACHED: 下次 read() 时触发重新拉取
  SUBSCRIBED → UNSUBSCRIBED: 会话结束或 Agent 显式取消
```

**订阅管理抽象：**
```
ResourceManager 抽象：
  ├── discover_resources(server_id) → ResourceCatalog
  ├── subscribe(resource_uri) → Subscription
  ├── read(resource_uri) → ResourceContent
  │   - 若在 CACHED 状态且未过期 → 返回缓存
  │   - 若在 STALE 状态 → 重新拉取后更新缓存并返回
  ├── on_update(resource_uri, callback) → None
  │   - 注册回调：Server 推送更新时触发
  └── unsubscribe(subscription) → None
```

---

## 工具发现缓存策略

每次 Agent 做工具调用前，重新发现工具列表（`list_tools`）是极大的浪费——典型场景中工具列表在整个会话中不变化。

```
发现缓存三层架构：
  Level 1 —— 内存缓存（Priority: 最高, TTL: 整个会话生命周期）
    ├── 首次 list_tools 结果存入内存
    ├── 后续所有 tool_use 块从内存缓存中查找工具定义
    └── 失效条件：Server 显式发送 tool_list_changed 通知

  Level 2 —— 会话缓存（Priority: 中, TTL: 当前 Session）
    ├── 跨轮次复用：同一 Session 内不重复发现
    └── 但每次 API 调用仍需将工具定义序列化到请求体

  Level 3 —— 动态发现（Priority: 低, TTL: 无缓存）
    ├── MCP Server 启动时、连接恢复时触发
    └── 仅在收到 tool_list_changed 通知时重新拉取
```

**关键规则：**
- `list_tools` 调用不进入 Agent 的 token 计费（Harness 层开销）
- 工具定义注入到 LLM 请求时受 Prompt Cache 前缀稳定性策略控制
- MCP 工具追加在稳定前缀之后，不破坏缓存

---

## 错误处理策略

```


### 指数退避 + 电路断路器

```
指数退避重试（Exponential Backoff）：

  重试序列：第 1 次 → 立即 | 第 2 次 → 1s | 第 3 次 → 2s | 第 4 次 → 4s
  最大重试次数：5
  最大等待时间：30s
  抖动因子：±25%（避免惊群效应）

  不可重试错误（立即放弃）：
    ├── ToolNotFound — 工具名称拼写错误或 Server 不支持
    ├── InvalidParams — 参数类型/格式错误
    ├── AuthError — Token 过期或无效
    └── PermissionDenied — 无权限执行

电路断路器（Circuit Breaker）：

  三个状态：
  ┌──────────┐  失败 > N 次  ┌──────────┐  冷却时间到期  ┌─────────────┐
  │  CLOSED  │ ─────────────→ │   OPEN   │ ─────────────→ │ HALF_OPEN   │
  │ (正常)   │                │ (熔断)   │                │ (试探恢复)   │
  └──────────┘                └──────────┘                └──────┬──────┘
       ↑                          ↑                            │
       │                          │                    成功 ← 试探请求
       │                          │                            │
       │                          │                    失败 ──→ 回到 OPEN
       └──────────────────────────┘
          失败计数重置（时间窗口滑动）

  参数：
    ├── 失败阈值（failureThreshold）：滑动窗口内 5 次失败 → 触发 OPEN
    ├── 冷却时间（cooldownPeriod）：30s 内保持 OPEN 状态
    ├── 试探请求数（halfOpenMaxRequests）：HALF_OPEN 状态最多允许 3 次试探
    └── 滑动窗口（windowSize）：60s 内累计失败数
```

**错误传播到 Agent：**
```
Harness 层错误 → Agent 层信息转换：

MCP 层错误              → Agent 可见信息
────────────────────────────────────────────
连接超时                → "工具 X 当前不可用：Server 未响应"
电路断路器熔断          → "工具 X 暂时被禁用：Server 近期多次失败，将在 30s 后自动重试"
ToolNotFound            → "工具 X 不存在：请检查工具名称和 Server 配置"
AuthError               → "工具 X 认证失败：请重新连接 MCP Server"
InvalidParams           → "工具 X 参数错误：{具体字段}格式不正确"
StaleCache              → "工具 X 返回了过期缓存结果：正在重新获取最新数据"
```

### MCP 错误 → ErrorKind 映射（与 `references/08-core-concepts.md` 对齐）

所有 MCP 层错误先 `classify_error → ErrorKind`（08 的五类：`retryable` / `fatal` / `degrade` / `replan` / `human_required`），再按处理契约分流。下表是 MCP 特有的五种典型错误归属：

| MCP 错误场景 | ErrorKind | 处理契约 | 说明 |
|--------------|-----------|----------|------|
| 连接超时（Connect Timeout） | `retryable` | 立即重试（带退避），耗尽升级 `fatal` | 瞬时网络抖动；退避上限受 06 的 Budget 约束 |
| 熔断（Circuit Breaker OPEN） | `retryable`（冷却后自愈；持续 OPEN 升级 `human_required`） | 冷却窗口到期自动半开试探 | 属"暂时不可用"，非结构性失败；长期不恢复说明 Server 失联需人工 |
| ToolNotFound | `human_required` | 挂起等待，不自动推进 | 工具注册 / 配置错误，重传同等参数必败；需人工修正 Server 注册 |
| AuthError | `human_required` | 挂起等待，重新授权 | 凭证失效需重新 OAuth / 换 Token；盲重试凭证无意义（见 OAuth 节） |
| InvalidParams | `replan` | 回到 Planner 重新生成合规参数 | 参数契约不符，同等参数重试必败；交由 Planner 重构调用 |

> 与 08 的「散文式错误 → ErrorKind 映射表」同源：permission deny（06 权限决策）→ `human_required`，不在 `retryable` 集合内。MCP 工具的 `idempotent` 声明决定副作用类错误能否安全重试（见 08 的「幂等性要求」）。

---

## 规模适应性指南

### Minimal（最小可行）

- 仅支持 stdio 传输（本地工具，零配置）
- 无连接池（每次调用启动子进程，用完销毁）
- 无 OAuth（所有 Server 在本地，不需要远程认证）
- 无资源订阅（仅支持工具的请求-响应模式）
- 简单重试：3 次固定间隔重试，无电路断路器
- 代码量：~200 行（直接调用 MCP SDK）

### Professional（专业级）

- stdio + Streamable HTTP 双协议支持（HTTP+SSE 仅遗留兼容）
- 连接池：min 2, max 5
- 资源生命周期：discover → subscribe → read（无自动更新推送）
- 工具发现缓存：Level 1 内存缓存（会话级）
- OAuth：支持 Authorization Code 流程
- 指数退避重试：5 次，最大 30s
- 代码量：~600-1000 行

### Enterprise（企业级）

- 全部传输协议可选（Streamable HTTP 远程默认；HTTP+SSE 仅遗留兼容；stdio 本地默认）
- 连接池：动态伸缩，基于负载自适应
- 电路断路器：完整三状态实现
- 资源生命周期完整 + Server 推送实时更新
- 工具发现缓存：三层架构 + `tool_list_changed` 通知自动失效
- OAuth：Authorization Code + PKCE + Token 自动刷新 + 凭据管理器存储
- 监控埋点：每 Server 的 QPS、P50/P99 延迟、错误率、缓存命中率
- 多区域支持：Server 就近路由（按 Client 地理位置选择最近的 Server 节点）
- 代码量：~1500-2500 行

---

## AI 构建提示

构建 MCP 集成层时，AI 不应直接复制代码，而应根据以下提示自行实现：

1. **传输层抽象**：先建 `Transport` 抽象接口——`connect()`, `send(message)`, `receive() → message`, `close()`。所有 6 种传输协议实现此接口。上层 `MCPClient` 只依赖 `Transport`，不感知底层协议。

2. **工具发现缓存**：使用 TTL Cache 模式。`list_tools` 结果缓存到内存，key = server_id，过期后自动重新拉取。Server 推送 `notifications/tools/list_changed` 时强制失效。

3. **OAuth 流程**：不要硬编码 client_id 和 client_secret。通过环境变量或操作系统凭据管理器注入。Token 刷新在后台自动执行，请求线程不感知。

4. **资源订阅**：使用观察者模式。`ResourceManager` 内部维护 `uri → Set<callback>` 的映射表。Server 推送更新时遍历回调列表通知所有订阅方。

5. **连接池**：使用对象池模式。不要自己从零实现池——若语言有成熟连接池库（如 Python 的 `aiopg`、TypeScript 的 `generic-pool`），优先复用而非自建。

6. **错误分类**：将 MCP 协议错误码映射到内部错误类型（NetworkError, AuthError, ToolError, ResourceError）。映射表可配置，方便扩展新错误码。

7. **测试策略**：
   - 单元测试：token 刷新逻辑（模拟过期）→ 验证自动刷新；连接池分配和归还 → 验证无泄漏
   - 集成测试：启动真实 MCP Server（stdio）→ 调用 list_tools → 调用每个工具 → 验证结果
   - 混沌测试：随机断开 Server 连接 → 验证重连和电路断路器行为

8. **监控埋点**：每个 `call_tool` 操作记录开始时间、结束时间、Server ID、工具名、结果状态（success/error/timeout）。这些指标用于电路断路器的决策和运维面板。