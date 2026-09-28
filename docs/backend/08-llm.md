# 08 LLM 网关与 trace（llm.py）

## 一、接口

```python
@dataclass
class LLMReply:
    raw: str                   # 模型原始输出文本（mock 也有）
    usage: dict                # {prompt_tokens, completion_tokens, cached_prompt_tokens}
    cost_micros: int           # 按座位单价折算
    latency_ms: int
    status: str                # ok | fallback

async def complete(seat_cfg, messages, *, purpose, match_id) -> LLMReply
```

`seat_cfg` 来自座位快照（[09-config.md](09-config.md)）：`model/base_url/api_key`（key 运行时
从环境变量解析进内存，绝不落库）+ 三个单价。`model == "mock"` 走内置 mock provider，
否则走 openai SDK。

## 二、mock provider（确定性，P3）

从 prompt 内容**反解**出回话所需信息，产出确定、有内容的回复——同 prompt 必得同回复：

1. 座位号：正则 `你是 (\d+) 号座位`；
2. 动作类型：指令层声明的 `action_type`；
3. 候选集：正则 `合法目标座位：\[([\d, ]+)\]`；
4. 回复构造：
   - `monologue`：`(mock) {seat} 号按 {action_type} 行动`；
   - `speech`：`我是 {seat} 号，{action_type} 环节发言（mock）。`；
   - `action`：`target = candidates[(seat * 3 + 5) % len(candidates)]`（候选非空时），
     register 类返回 `yes = seat ∈ {3, 6, 9}`，无候选的动作 target=0。

mock 的存在价值：**e2e 确定性测试**与无 key 冒烟。公式本身无游戏含义，但必须稳定——
换公式 = 换测试期望，公式写进测试锁死。

## 三、真实调用（openai SDK，语义沿用 S4/D28.3）

- 超时 60s/次；重试 ≤2（退避 2s/5s）；
- 可重试异常**显式包含** openai SDK 的 `APIConnectionError / APITimeoutError /
  RateLimitError / InternalServerError`，以及 HTTP 429/5xx——它们不继承内置异常，
  只捕内置等于生产从不重试（历史 bug）；
- 4xx（参数错/鉴权失败）不重试，直接失败；
- 坏 JSON 的**修复调用**（07）共享同一重试循环；每个原始响应只修复一次；
- 每次尝试（含失败）都落一行 `llm_call`（status 区分），重试耗尽后向 agent 抛出，
  由 agent 记 `player.fallback`。

## 四、用量计量与计费（沿用）

- usage 归一：OpenAI 系 `prompt_tokens_details.cached_tokens`、DeepSeek 系顶层
  `prompt_cache_hit_tokens` → 统一 `cached_prompt_tokens`；取不到按 0（全量未命中）；
- `cost_micros = uncached_in × price_in + cached_in × price_cached_in + completion × price_out`
  （单价单位：每百万 token；`price_cached_in` 缺省等于输入价；`cached > prompt` 时按 0 计
  uncached，防死负数）；
- mock 调用也计量（prompt 按字符数 ÷4 估，completion 按输出长度估，cost 恒 0），
  保证用量面板对两种模式同构。

## 五、trace（--trace DIR，P4）

开启后每局写一个 `DIR/match-<id>.jsonl`，**逐条 append**（跑挂了也已落盘的部分可用）：

```jsonc
{"t": "call", "ts": "...", "seat": 3, "purpose": "vote", "phase": "day_vote",
 "messages": [...],            // 六层拼装后的完整 prompt（唯一能回看「当时模型看到什么」的地方）
 "raw": "...", "parsed": {...}, "action": {...}, "fell_back": false,
 "usage": {...}, "cost_micros": 0, "latency_ms": 812}
{"t": "event", "event": {…}}   // 每条事件落库时同步记录
{"t": "phase", "phase": "wolf_meeting", "state": {…snapshot…}}   // 阶段结束状态快照
{"t": "rule_error", "phase": "...", "reason": "..."}
```

trace 目录不入 git（`.gitignore`）；`llm_call` 表只存数字摘要，原文只在 trace——
DB 面向统计，trace 面向排障。
