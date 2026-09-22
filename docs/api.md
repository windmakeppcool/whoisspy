# API 契约

REST + SSE；所有事件出站走同一可见性过滤（[events-storage.md](events-storage.md)）。

## 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/matches` | 创建对局并异步开跑 |
| GET | `/api/matches` | 对局列表（状态/结果/时间） |
| GET | `/api/matches/{id}` | 对局详情（板子、座位、状态、结果） |
| GET | `/api/matches/{id}/events` | 事件回放，参数 `after_seq=`、`view=` |
| GET | `/api/matches/{id}/stream` | SSE 追更，参数 `view=immersive|god` |
| GET | `/api/matches/{id}/usage` | 用量汇总（token/费用/调用数） |
| POST | `/api/matches/{id}/stop` | 终止进行中的对局 |
| GET | `/api/catalog/boards` | 板子预设 |
| GET | `/api/catalog/personas` | 选手档案 |
| GET | `/api/catalog/providers` | 接入预设（脱敏） |

## POST /api/matches 请求体

```json
{
  "game_type": "werewolf",
  "board": { "id": "p6-classic" },
  "seats": [
    {
      "persona_id": "aggressive-liar",
      "base_url": "https://api.example.com/v1",
      "api_key_env": "PLAYER1_API_KEY",
      "model": "model-a"
    },
    { "provider_ref": "demo/model-b", "persona_id": "calm-analyst" }
  ]
}
```

- 座位支持两种写法：全量四字段（D10 座位级独立 key），或 `provider_ref` 引用 providers.json 预设展开固化。
- `board` 可用预设 id 或 `{ "roles": { ... } }` custom（服务端 validate_board 校验）。
- 校验失败 422；校验通过即生成 rng_seed 落 `match.created`，异步启动 MatchRunner。

## SSE 帧格式

```
id: 42
event: game_event
data: {"seq": 42, "type": "player.speech", "day_index": 2, "phase": "day_speech", "payload": {...}}
```

- `id: <seq>` 即游标；断线重连带 `Last-Event-ID` 先补发后订阅。
- `view` 决定过滤强度：immersive 只发 public（+本视角 seat——v1 观众无座位则纯 public）；god 全发。
- 错误帧 `event: error`；对局结束发 `event: match_finished`。
