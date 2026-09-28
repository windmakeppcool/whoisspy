# 07 Agent 调用协议与容错链（agent.py）

`agent.py` 是「问一个座位」的唯一实现：组 prompt（06）→ 调网关（08）→ 解析 → 校验 → 兜底。
flow 只消费 `(action, reply, fell_back)` 三元组，不感知细节。

```python
@dataclass
class AskSpec:
    action_type: str          # 期望的动作类型（kill/check/save/vote/speech/register/...）
    prompt: str               # 指令文本（06 第三节模板）
    prompt_extra: str = ""    # 附加语义（女巫刀口句等），落指令层
    candidates: list[int] = field(default_factory=list)  # 合法目标（进 prompt 与校验）

@dataclass
class AgentReply:
    monologue: str = ""
    speech: str = ""
    action: dict = field(default_factory=dict)
```

## 一、调用管线

```
ask(run, seat, spec, purpose):
  1. messages = build_user_prompt(...)            # 六层（06）
  2. reply = gateway.complete(seat_cfg, messages, purpose)   # 网络/重试在网关内闭环（08）
     失败（重试耗尽）→ 落 player.fallback {seat, reason, purpose}（god）
                      → return (neutral_action(phase), AgentReply(空), fell_back=True)
  3. parsed = parse_agent_response(reply.raw)     # 严格 JSON → 一次修复调用 → 仍坏按失败（同上路径）
  4. action = rules.validate_action(state, phase, spec, parsed.action)   # 非法 → 中性（05 七）
     校验代码自身抛异常 → 落 rule.error {phase, reason}（god）→ 中性动作
  5. return (action, parsed, False)
```

要点：

- **三层失败三种记账**，绝不混同（P4，沿用 D28.4 语义）：
  网关失败/坏 JSON → `player.fallback`；规则代码崩溃 → `rule.error`；LLM 输出非法 → 无事件（正常降级）。
- 修复调用（坏 JSON 的「重答一次格式」）由网关内部处理，包括它自己撞上可重试错误时回到外层重试（D28.3）。
- `monologue` 每次成功调用都要求产出（D6 言行对照是节目核心）；为空则不落 `player.monologue`。

## 二、JSON 输出协议（D22 沿用）

```json
{ "monologue": "真实判断、盘算、谎言意图（god 可见）",
  "speech": "对外发言（发言类调用）",
  "action": { "type": "vote", "target": 3 } }
```

字段顺序即生成顺序：monologue 先（先盘算）→ speech 后（再决定说什么）→ action。
解析链：严格 `json.loads` → 失败做**一次**格式修复调用（修复提示中的 schema 与本契约同序）
→ 仍失败走中性兜底。

## 三、240 字发言上限

prompt 声明上限（overview 切片）；执行侧在 flow 落 `player.speech`/`player.last_words` 时
把文本截到 240 字——确定性、可测试，不依赖模型自觉。
