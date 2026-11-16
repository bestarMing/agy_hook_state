# Spec: agy CLI 对话延迟与吞吐量 Hook

> 返回地图：[Map: agy CLI 延迟/吞吐量 hook 设计规格](https://github.com/bestarMing/agy_hook_state/issues/1)
>
> 状态：**可交接**（设计决策已全部锁定；实现留给下一程）。本 spec 只定义"做什么、怎么算、什么形状"，不含实现代码。

---

## 1. 目标与范围

为 `agy`（Google Antigravity CLI）设计一个 hook，计算对话的**延迟**与**吞吐量**，结果落本地 JSONL 按会话存档，并在终端显示一行摘要。

- **终点**：一份可交接、可迭代的设计规格。实现代码、发布分发、CI、跨平台适配细节均 **out of scope**（见地图 Out of scope）。
- **边界**：以 hook 为触发与墙钟采集主体，**辅以** transcript.jsonl 交叉校验与用户自建 statusline→sidecar 桥取 token；**不采用** stream-json 包装器（chart 阶段已排除）。
- 术语遵从 [`GLOSSARY.md`](../../GLOSSARY.md)；关键架构权衡见 [`docs/adr/0001-statusline-sidecar-bridge.md`](../adr/0001-statusline-sidecar-bridge.md)。

## 2. 术语与数据来源

### 术语（详见 GLOSSARY.md）

严格嵌套：**会话 Session ⊃ 轮次 Turn ⊃ 调用 Invocation**。核心指标：**Turn Latency**（轮次端到端延迟）、**Invocation Duration**（调用耗时）、**TTFT**（首 token 延迟，本架构恒 unknown）、**Output Throughput**（输出吞吐量）、**Input Token Count**（输入 token 数）。

### 数据来源与可信度（来自研究票，[完整事实清单](../../docs/research/agy-hook-telemetry-facts.md)，分支 `research/hook-telemetry-facts`）

| 源 | 提供 | 可信度 |
|---|---|---|
| Hook 载荷（stdin） | conversationId、transcriptPath、invocationNum、executionNum、modelName 等**计数器**；**无任何时间戳/token 字段** | 官方+一手证实 |
| Hook 自打墙钟 | 各事件触发时的系统时钟 | 本方案主时钟（唯一可控） |
| statusline `context_window` | total_input/output_tokens、current_usage、cost | 官方证实字段；"累计"为推断；独立通道 |
| transcript.jsonl | step 级 `created_at` | 仅路径官方证实；行结构/时间格式**第三方未证实**，只作交叉校验 |
| stderr 安全性 | — | **未文档化** → 本方案不依赖 |

## 3. 架构与数据流（三通道汇合）

1. **权威时钟 = hook 自打墙钟**。每个 hook 事件进程把 `{conversationId, event, invocationNum, executionNum, wallClockMs}` 追加到按 conversationId 分区的事件日志；`invocationNum` 配对 Pre/Post，`executionNum` 标记轮次。
2. **token 来源 = 用户自建 statusline→sidecar 桥**（ADR-0001）。statusline 命令把 `context_window` token 快照写入 sidecar，Stop hook 读取。此为非官方组件、待验证假设；放弃 token 会使吞吐目标落空，stream-json 已出 scope，故接受该桥。
3. **汇聚点 = Stop hook**。每轮最后一次 Stop（`continuation_active=false` 且 `decision≠continue`）时，合并三通道数据算指标、落记录。
4. **状态按 conversationId 分区**，存 `~/.gemini/antigravity-cli/hook-metrics/<conversationId>/`，天然隔离并发会话。
5. **输出通道**：一行摘要写专用 sidecar 文件，由 statusline 命令显示——statusline stdout 是已文档化的显示通道，**不赌未文档化的 stderr**（详见 §5、§6）。

## 4. 指标算法

### 4.1 单指标公式

| 指标 | 公式 / 定义 | 无值状态 |
|---|---|---|
| Turn Latency | 终态 Stop 墙钟 − 该轮首个 PreInvocation 墙钟 | 任一墙钟缺失 → `null` |
| Invocation Duration | 同一 invocationNum 的 PostInvocation 墙钟 − PreInvocation 墙钟 | 缺一 → `null` |
| TTFT | 不计算（本架构无法取得首 token 时间） | 恒 `"unknown"` |
| Output Throughput | `Δ total_output_tokens ÷ Σ(Post−Pre)`（分母=模型活跃时间，含思考、不含工具间隙） | 差值为负/缺失或分母为 0 → `"unknown"` |
| Input Token Count | statusline 桥 token 快照 | 源缺失 → `"unknown"` |

- transcript `created_at` 仅交叉校验；偏差 > 2s 记 warning，**不改权威墙钟值**。
- 轮次记录并列存 `turnLatency`（权威）、`invocationDurations[]`、`invocationCount`；不用调用耗时之和冒充 Turn Latency。
- 三种哨兵严格区分、不混用：`null`（本应有但采集失败）、`"unknown"`（架构算不出）、数字（真值）。

### 4.2 多轮聚合（派生，非逐条存储）

- 延迟：**p50 / p95 + 总和**（延迟右偏，均值误导）。
- 吞吐：**总 output token ÷ 总模型活跃时间**（比率之比，**不是**各轮吞吐的算术平均）。

## 5. 数据格式与存储

### 5.1 归档 JSONL（每轮一条）

路径：`~/.gemini/antigravity-cli/hook-metrics/<conversationId>.jsonl`（每会话一文件，无需轮转）。字段：

`schemaVersion, conversationId, turnIndex, timestamp, modelName, turnLatencyMs, invocationCount, invocationDurationsMs[], activeTimeMs, outputTokens, inputTokens, throughputTokensPerSec, ttftMs, completeness, missing[], crossCheck{}`

完整样例（三档：full / partial / empty）见 [`docs/prototypes/jsonl-schema-and-summary.md`](../prototypes/jsonl-schema-and-summary.md)（分支 `prototype/jsonl-schema`）。

### 5.2 一行终端摘要（终态 Stop hook 时打印）

```
agy c-7f3a turn#2  7.24s  p50 5.21s  out 412 tok  85.5 tok/s  in 1.9k  [full]
```

字段：conversationId 短名 · turnIndex · turnLatency · 会话 p50 · outputTokens · throughput · inputTokens · completeness（partial 时附 `missing`）。`ttftMs` 恒 unknown，不展示。

## 6. 配置契约

> 本节描述"需要什么配置"，不描述"如何安装分发到用户机器"（后者 out of scope）。

- **hooks.json**（workspace `.agents/hooks.json` 或全局 `~/.gemini/config/hooks.json`）注册：
  - `SessionStart`：开会话（可选，用于会话边界）。
  - `PreInvocation` / `PostInvocation`：调用边界墙钟打点，用 `invocationNum` 配对。
  - `Stop`：汇聚点——合并数据、算指标、落记录、写摘要 sidecar。
- **statusline 命令**（`settings.json`）承担两项职责：
  1. 取 token：把 `context_window` 快照写入 `<conversationId>.tokens.json`（ADR-0001）。
  2. 显示摘要：读 `<conversationId>.summary` 并打印到 stdout（已文档化显示通道）。
- hook 超时默认 30s；stdout 必须返回合法 JSON、退出码 0，否则 fail-open。

## 7. 错误与边界

| 场景 | 处理 |
|---|---|
| token 缺失（statusline 被 300ms 节流 / 30 次连续失败禁用 / 文件未写） | 该轮仍落记录，token 类指标标 `"unknown"`、`completeness:"partial"`、`missing:["tokens"]` |
| 缺首个 PreInvocation 或终态 Stop（会话崩溃） | Turn Latency = `null`、`completeness:"empty"`、仍落盘便于对账 |
| transcript 写到一半 / 行结构解析失败 | 不影响墙钟延迟；跳过 crossCheck，记 warning |
| 并发会话 / 多 workspace | 按 conversationId 分区，互不串数据 |
| hook 超时 / 非法 JSON / 非零退出 | CLI fail-open；本方案保证正常路径返回合法 JSON + 退出 0 |
| stderr 输出 | 不依赖（未文档化）；摘要走 statusline sidecar |

**绝不因单一指标缺失丢弃整轮**——延迟数据本身有价值。

## 8. 验证方法

算法票已给出可对账公式。验证步骤模板（真实 transcript 样本为实现期产物，不在本 spec 内生成）：

1. 取一个已知 conversationId 的完整 `transcript.jsonl` + 对应 hook 事件日志 + token 快照。
2. 手工计算该轮 Turn Latency、各 Invocation Duration、Output Throughput（用 §4 公式）。
3. 与归档 JSONL 记录比对：延迟值应一致（容差内）；transcript `created_at` 交叉校验偏差应 < 2s，否则有 warning。
4. 注入故障（删 token 快照 / 制造无 Stop 会话）验证 §7 的 partial / empty 记录正确落盘、哨兵值正确。
5. 验证 statusline 摘要显示正确、hook stdout 始终为合法 JSON。

## 9. 未决假设与待验证

以下按约定写入 spec、**不阻塞交接**，实现期需实测确认：

- **transcript.jsonl 行结构与 `created_at` 精度/时区**：仅第三方单一例子，未获官方文档证实；仅作交叉校验，不影响核心指标。
- **statusline `total_*_tokens` 是否累计**：docs 从未明说，基于 `total_` 命名与 `current_usage` 并存的推断；实现期需用真实会话验证做差逻辑。
- **statusline→sidecar 桥的文件写入时机与 300ms 节流**：需实测 Stop hook 读取时 token 快照是否就绪，否则该轮退化为 partial。
- **stderr 安全性**：未文档化，本方案已绕过（statusline 显示），无需验证即可安全。

## 10. 决策索引

| 决策 | 票 | 产物 |
|---|---|---|
| 术语与三层边界 | [#3](https://github.com/bestarMing/agy_hook_state/issues/3) | `GLOSSARY.md` |
| hook/遥测精确事实 | [#2](https://github.com/bestarMing/agy_hook_state/issues/2) | 分支 `research/hook-telemetry-facts` 的事实清单 |
| 采集架构与三通道汇合 | [#4](https://github.com/bestarMing/agy_hook_state/issues/4) | ADR-0001 |
| 延迟与吞吐量算法 | [#5](https://github.com/bestarMing/agy_hook_state/issues/5) | 本 spec §4 |
| JSONL schema / 路径 / 摘要 | [#6](https://github.com/bestarMing/agy_hook_state/issues/6) | 分支 `prototype/jsonl-schema` 的样例 |
| spec 组装与验收 | [#7](https://github.com/bestarMing/agy_hook_state/issues/7) | 本文件 |
