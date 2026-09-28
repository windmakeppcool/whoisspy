# 11 导出与观赛文案（present.py · export.py）

`present.py` 是「事件 → 人话」的**唯一**渲染处（P5）：导出 JSON、CLI 终端直播、
未来的任何展示端都消费它，客户端不允许自带事件解释逻辑。

```python
@dataclass
class Line:
    kind: str        # speech | last_words | monologue | channel | system | vote | phase
    seat: int | None
    text: str

def present(ev: Event) -> Line | None: ...   # 纯函数；None = 不上屏
```

## 一、观赛文案表（present 唯一权威）

| 事件 | 观赛行 |
|---|---|
| `phase.started` | `—— {label}（第 {day} 天）——` |
| `player.speech` | `{seat} 号：{text}` |
| `player.last_words` | `{seat} 号（遗言）：{text}` |
| `channel.message` | `{seat} 号（狼队频道）：{text}` |
| `player.monologue` | `{seat} 号（内心）：{text}` |
| `night.kill_target` | `狼队选择击杀 {target} 号` / `狼队空刀` |
| `night.seer_query` | `预言家查验 {target} 号`（target=0 → `预言家今晚未查验`） |
| `night.seer_result` | `查验 {target} 号：狼人` / `查验 {target} 号：好人` |
| `night.witch_action` | `女巫使用解药` / `女巫毒杀 {target} 号` / `女巫不用药` |
| `night.resolved` | `第 {day} 夜：X 号、Y 号 死亡` / `第 {day} 夜：平安夜` |
| `night.death_cause` | `死因：X 号=刀杀、Y 号=毒杀` |
| `skill_state.notice` | `{seat} 号猎人：可以开枪` / `今晚不能开枪` |
| `sheriff.registered` | `上警：X 号、Y 号` / `无人上警` |
| `sheriff.badge` | `X 号当选警长` / `警徽移交给 X 号` / `警徽被撕毁` |
| `day.speech_order` | `发言顺序：X→Y→Z 号` |
| `vote.cast` | `X 号投票给 Y 号` / `X 号弃票` |
| `vote.resolved`（exile） | `X 号被放逐出局` / `平票，无人出局` |
| `vote.resolved`（sheriff） | `X 号当选警长` / `警长投票平票` |
| `gun.shoot` | `X 号开枪带走 Y 号` / `X 号放弃开枪` |
| `player.fallback` | `⚠ {seat} 号调用失败走兜底（{reason}）` |
| `rule.error` | `⚠ 规则异常（{phase}）：{reason}` |
| `match.finished` | `🏁 对局结束：{阵营}获胜（{reason}）` |
| `match.stopped` | `⏹ 对局终止：{reason}` |
| `role.dealt` | `发牌：{seat} 号 = {role}`（**god 视角才有**） |

文案微调只改 present.py 一处——这是「单一归属」的验收标准。

## 二、视角过滤

导出与直播共用同一过滤规则（vis 落库值是唯一依据）：

- **god 视角**：全量事件；
- **public 视角**：只保留 `vis.level == "public"` 的事件（狼队频道/夜晚操作/独白/兜底/发牌全不可见）。

## 三、导出 JSON schema（export.py）

```
exports/match-<id>-<view>.json
```

```jsonc
{
  "match_id": 1,
  "exported_at": "2026-09-25T…Z",
  "view": "god",
  "match": {                       // 元信息
    "seed": 42, "status": "finished",
    "winner": "good", "reason": "狼人全部出局",
    "board": { "roles": {…}, "wolf_meeting_rounds": 2, "max_days": 8 },
    "seats": [ { "seat": 1, "persona_id": "…", "model": "…", "role": "wolf" } ],  // role 仅 god
    "model_assignments": [ … ]
  },
  "segments": [                    // 分段：开局 / 第N夜 / 第N天
    { "label": "开局",   "day_index": 0, "entries": [ …Line ] },
    { "label": "第一夜", "day_index": 1, "entries": [ … ] },
    { "label": "第一天", "day_index": 1, "entries": [ … ] }
  ],
  "usage": { "calls": 97, "prompt_tokens": …, "completion_tokens": …,
             "cached_prompt_tokens": …, "cost_micros": …, "cache_hit_rate": 0.62,
             "fallbacks": 3, "rule_errors": 0 }
}
```

分段规则：

1. `day_index == 0` 的事件（match.*/role.dealt）归「开局」段；
2. 之后按 `(day_index, is_night)` 变化切段：`is_night` 由阶段归属决定（[03-events.md](03-events.md)
   第二节「夜/昼」列；**警长竞选归当夜**）；
3. 段内 `entries` = 逐事件 `present()` 结果（None 跳过），保持事件序。

`usage.fallbacks / rule_errors` 从事件流计数（god 事件数）——「这局有多少动作是兜底产生的」
在导出文件里一眼可见（旧系统无此汇总，排查全兜底假局全靠翻库）。

## 四、终端直播（CLI 运行时）

跑局过程中每落一条事件，立即把 `present(ev)` 打到 stdout（god 视角、单行式，
不整屏刷新——保留滚动历史便于盯流程）；导出文件是同一投影的持久化形态。
