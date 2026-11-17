# agy 对话延迟与吞吐量 Hook

为 `agy`（Google Antigravity CLI）提供一套采集与计算方案：在每轮对话结束时，算出**轮次端到端延迟**、**每次调用耗时明细**、**输出吞吐量**与**输入 token 数**，按会话归档为 JSONL，并在状态栏显示一行摘要。

仓库为 greenfield 实现，仅用 Python 标准库，遵循 `GLOSSARY.md` 中的领域术语。设计决策见 [Spec #8](https://github.com/bestarMing/agy_hook_state/issues/8)、[ADR-0001](docs/adr/0001-statusline-sidecar-bridge.md) 与 [完整规格](docs/specs/latency-throughput-hook.md)。

## 它解决什么问题

`agy` 的 hook 载荷里既没有时间戳也没有 token 计数（官方证实）。因此延迟和吞吐量不能靠读现成字段，必须自己采集：

- **权威时钟**：hook 事件触发时的系统墙钟，每个事件打上 `{conversationId, event, invocationNum, wallClockMs}`。
- **轮次边界**：用 `invocationNum` 配对 PreInvocation/PostInvocation 得到调用边界；以终态 Stop（`continuation_active=false` 且 `decision≠continue`）为轮次终点，以该轮首个 PreInvocation 为起点。
- **token 来源**：通过用户自建的 **statusline→sidecar 桥**（[ADR-0001](docs/adr/0001-statusline-sidecar-bridge.md)）——statusline 命令把 token 快照写入按会话分区的 sidecar 文件，Stop hook 读取。这是本方案对非官方组件的刻意依赖；没有它就没有 token 数据。
- **TTFT** 本架构无法取得，恒为 `"unknown"`，不伪造数字。

## 目录结构

| 路径 | 作用 |
| --- | --- |
| `agy_metrics/clock.py` | 可注入时钟 `Clock` / `SystemClock` / `FakeClock` |
| `agy_metrics/schema.py` | 哨兵 `NULL` / `UNKNOWN`、`SCHEMA_VERSION`、`Completeness`、`TurnRecord` |
| `agy_metrics/storage.py` | 全部文件 I/O：分区路径、事件日志、归档、token 快照、摘要 sidecar |
| `agy_metrics/metrics.py` | 纯计算：配对调用、算指标、三哨兵、聚合、摘要文本 |
| `agy_metrics/core.py` | 单一 seam `handle_event(...)`：追加事件、终态 Stop 汇聚成轮次、落归档与摘要 |
| `agy_metrics/hook_command.py` | hook 命令壳：stdin JSON → stdout `{}`、exit 0、fail-open |
| `agy_metrics/statusline.py` | 状态栏命令壳：写 token 快照 + 显示摘要 |
| `agy_metrics/install.py` | 一键安装：生成 launcher、合并 hook/statusLine 配置 |
| `config/` | 两份配置示例（见下） |
| `tests/` | 22 个规格测试 + 4 个审查修复测试 + 7 个安装测试，共 33 个 |

架构上只有一个核心模块（采集/计算/落盘）和两个薄壳（hook 壳、statusline 壳），薄壳只做 JSON 编解码与调度，不含业务逻辑。所有测试都通过单一 seam `handle_event(event, base_dir, clock)` 做外部行为断言。

## 环境要求

- Python **>= 3.11**
- **仅标准库**，无第三方依赖（`pyproject.toml` 中 `dependencies = []`）
- 包名为 `agy_metrics`，命令通过 `python -m agy_metrics.<模块>` 调用

## 安装与配置

### 一键安装（推荐）

在仓库根目录跑一条命令即可，无需手动改配置文件：

```bash
python -m agy_metrics.install
```

脚本会：

1. 生成一个使用**绝对路径**的 launcher（内含仓库路径，不依赖当前工作目录，也不依赖 `PYTHONPATH` 或 `pip install`），所以 CLI 从任意目录用 `sh -c` / `cmd /c` 触发命令都能正确导入包；
2. 把四个 hook 事件合并进 `~/.gemini/config/hooks.json`；
3. 把 statusLine 命令合并进 `~/.gemini/antigravity-cli/settings.json`；
4. **幂等**（重复运行不会重复写入），并在改动前把原配置备份为 `.bak`。

覆盖用户目录用 `--home`（如 `python -m agy_metrics.install --home /path/to/home`）。装完**重启 agy** 生效。`AGY_METRICS_DIR` 可指定状态目录，默认 `~/.gemini/antigravity-cli/hook-metrics`。

> 脚本不支持自动解析无效 JSON：若现有配置不是合法 JSON，会报错退出且不覆盖原文件。请先手动修复或备份该配置。

### 手动配置（了解原理 / 排错用）

若你更想自己写配置，或脚本不适用，按下面两步来。关键是命令必须能在**任意 cwd** 下导入 `agy_metrics`——用 launcher 或可编辑安装（`pip install -e .`）都行；`cd` 到仓库根目录或设 `PYTHONPATH` 只在特定 cwd 下有效，不可靠。

**1. hooks.json**（全局 `~/.gemini/config/hooks.json`，或 workspace `.agents/hooks.json`）——注册四个事件，指向 hook 壳：

```json
{
  "SessionStart":   [{ "hooks": [{ "type": "command", "command": "<python> <launcher> hook", "timeout": 30 }] }],
  "PreInvocation":  [{ "hooks": [{ "type": "command", "command": "<python> <launcher> hook", "timeout": 30 }] }],
  "PostInvocation": [{ "hooks": [{ "type": "command", "command": "<python> <launcher> hook", "timeout": 30 }] }],
  "Stop":           [{ "hooks": [{ "type": "command", "command": "<python> <launcher> hook", "timeout": 30 }] }]
}
```

`<python>` 为 Python 解释器绝对路径，`<launcher>` 为一键脚本生成的 `~/.gemini/antigravity-cli/agy_metrics_launcher.py`（或等价地把仓库根目录 `sys.path.insert` 进去的启动器）。hook 壳把 CLI 传入的 JSON 交给核心处理，**stdout 始终只输出 `{}`、退出码恒为 0、失败即 fail-open**。

**2. settings.json**（`~/.gemini/antigravity-cli/settings.json`）——statusLine 必须是对象（不是布尔）：

```json
{
  "statusLine": { "type": "command", "command": "<python> <launcher> statusline" }
}
```

statusline 命令承担两项职责：把 `context_window` token 快照写入 sidecar（供 Stop hook 读取），并把上一轮的摘要打印到状态栏。摘要**只走 statusline 的 stdout**，不写 hook 的 stdout/stderr。

> 注意字段命名差异：hook 载荷用 `conversationId`（驼峰），statusline 载荷用 `conversation_id`（下划线）。两者须指向同一会话，token 桥才能正确汇合。这是 CLI 两个通道各自的既有契约，不是本项目自定义。

## 数据落在哪里

所有状态按会话隔离，位于 `$AGY_METRICS_DIR`（默认 `~/.gemini/antigravity-cli/hook-metrics`）下：

```
hook-metrics/
├── <conversationId>/            # 该会话的工作目录
│   ├── events.jsonl             # 追加的 hook 事件日志（含墙钟与 baseline token）
│   ├── tokens.json              # statusline 写入的最新 token 快照
│   └── summary.txt              # 供 statusline 显示的一行摘要
└── <conversationId>.jsonl       # 归档：每轮一行 TurnRecord
```

每轮归档记录（`TurnRecord`）字段：`schemaVersion`、`conversationId`、`turnIndex`、`timestamp`、`modelName`、`turnLatencyMs`、`invocationCount`、`invocationDurationsMs[]`、`activeTimeMs`、`outputTokens`、`inputTokens`、`throughputTokensPerSec`、`ttftMs`、`completeness`、`missing[]`、`crossCheck{}`。

**三种哨兵，绝不混用**：

- `null`：本应有但采集失败（如缺墙钟）
- `"unknown"`：本架构永远算不出（如 `ttftMs`，恒为 `"unknown"`）
- 数字：真实值

`completeness` 取值 `full` / `partial` / `empty`；`missing[]` 列出缺失项名（如 `["tokens"]`）。会话崩溃导致缺终态 Stop 时，`turnLatencyMs` 为 `null`、`completeness:"empty"`，仍落一行以便对账。

**摘要格式**（写在 `summary.txt`，由 statusline 显示）：

```
agy <conversationId> turn#<n>  <延迟>s  p50 <ms>s  out <n> tok  <速率> tok/s  in <n>k  [completeness]
```

会话级延迟用 p50/p95 聚合，吞吐用「总输出 token ÷ 总模型活跃时间」的比率之比（不是各轮速率的算术平均）。

术语定义（Session / Turn / Invocation、Turn Latency、Invocation Duration、TTFT、Output Throughput、Input Token Count 及其 Avoid 词）见 [`GLOSSARY.md`](GLOSSARY.md)。

## 运行测试

```bash
python -m unittest discover -s tests -v
```

预期 **33 tests OK**。测试用临时目录隔离状态、注入 `FakeClock` 让延迟断言确定性，只断言归档记录与摘要文本等外部行为，不断言核心内部中间结构；安装测试还会实际从无关 cwd 启动 launcher，验证绝对路径命令确实可用。

## 已知限制与待验证假设

- **崩溃无终态 Stop 时**：事件驱动 seam 没有「崩溃事件」可触发写盘；已实现且测试覆盖的空记录路径是「有 Stop 但无 PreInvocation」。
- **三个待验证假设**（实现期实测，不阻塞，降级路径见 Spec）：transcript 行结构与 `created_at` 精度/时区；statusline `total_*_tokens` 是否累计；statusline→sidecar 桥写入时机与 300ms 节流（Stop 读取时快照是否就绪，否则退化为 `partial`）。
- transcript `created_at` 仅作交叉校验：偏差 > 2s 记 warning，但不改权威墙钟值。

## 参考文档

- [Spec #8](https://github.com/bestarMing/agy_hook_state/issues/8) — 需求与实现决策
- [`docs/specs/latency-throughput-hook.md`](docs/specs/latency-throughput-hook.md) — 完整规格
- [`docs/adr/0001-statusline-sidecar-bridge.md`](docs/adr/0001-statusline-sidecar-bridge.md) — token 桥决策（不可随意「简化」掉）
- [`docs/research/agy-hook-telemetry-facts.md`](docs/research/agy-hook-telemetry-facts.md) — hook 与遥测事实清单
- [`docs/prototypes/jsonl-schema-and-summary.md`](docs/prototypes/jsonl-schema-and-summary.md) — JSONL schema 与摘要样例
- [`docs/superpowers/plans/2026-11-16-latency-throughput-hook.md`](docs/superpowers/plans/2026-11-16-latency-throughput-hook.md) — 实施计划
- [`GLOSSARY.md`](GLOSSARY.md) — 领域术语
