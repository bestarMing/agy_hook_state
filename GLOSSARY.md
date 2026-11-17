# agy 延迟/吞吐量观测

本仓库为 `agy`（Antigravity CLI）设计对话延迟与吞吐量 hook 时使用的领域术语。本文件只定义概念，不涉及数据来源或计算实现。

## 计时单位

**会话 Session**:
一个对话的完整生命周期，是最粗的计时单位。一个会话包含一个或多个轮次。
_Avoid_: conversation、对话

**轮次 Turn**:
从用户一次提问到 agent 停止并等待下一条输入之间的区间。轮次之间以用户的新提问分隔；一个轮次包含一次或多次调用。
_Avoid_: round、回合

**调用 Invocation**:
一次模型请求与响应的往返，是最细的计时单位。一个轮次由一次或多次调用组成。
_Avoid_: model call、request

## 指标

**轮次端到端延迟 Turn Latency**:
一个轮次从起点（用户提问）到终点（agent 停止等待输入）的持续时间。
_Avoid_: response time

**调用耗时 Invocation Duration**:
单次调用从发出请求到收到完整响应的持续时间。

**模型活跃时间 Active Time**:
一个轮次中所有调用耗时的累计总和，代表模型处于请求与生成状态的时间。
_Avoid_: model time、生成时间

**工具执行耗时 Tool Execution Time**:
一个轮次中执行外部工具与命令的累计耗时，等于轮次端到端延迟减去模型活跃时间。
_Avoid_: tool duration、工具耗时

**思维链耗时 Thinking Duration**:
单次调用中模型生成内部思维链（Chain-of-Thought / Thinking）内容的物理持续时间。
_Avoid_: 思考时间、CoT 耗时、reasoning time

**首 token 延迟 Time to First Token (TTFT)**:
从用户提问到该轮首个输出 token 出现的延迟，衡量响应的起始速度。

**输出吞吐量 Output Throughput**:
单位模型活跃时间内产出的输出 token 数，衡量模型的生成速度。模型活跃时间指模型处于生成状态的时间，不含工具执行间隙。输入 token 不计入本指标。
_Avoid_: TPS、吞吐率

**输入 token 数 Input Token Count**:
一个轮次消耗的输入 token 总量，与输出吞吐量分开报告。
