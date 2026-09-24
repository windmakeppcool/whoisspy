# API 契约

REST + SSE；所有事件出站走同一可见性过滤（`core.filtered_view`，[events-storage.md](events-storage.md)）。
默认只绑定 `127.0.0.1`；安全约束见 [configuration.md](configuration.md)。

## 启动入口

- API 服务：`python -m app.main [--port N]`（uvicorn，默认 8000）。
- TUI 观看器：`python -m app.main --tui [--match-id N] [--board p9-standard] [--port N]`——
  同进程先拉起 API 再打开终端视图，走本页同一套 REST/SSE（D16）。

## 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/matches` | 创建对局并异步开跑（校验失败 422） |
| GET | `/api/matches` | 对局列表（状态/结果/时间，含座位快照） |
| GET | `/api/matches/{id}` | 对局详情（板子、座位、状态、结果） |
| GET | `/api/matches/{id}/events` | 事件回放，参数 `after_seq=`（缺省读 `Last-Event-ID` 头）、`view=` |
| GET | `/api/matches/{id}/stream` | SSE 追更，参数 `view=immersive|god`、`last_event_id=`（缺省读头） |
| GET | `/api/matches/{id}/usage` | 用量汇总（token/费用/调用数/缓存命中率）；对局不存在 404 |
| GET | `/api/matches/{id}/export` | 整局对话 JSON 导出（上帝视角，附件下载） |
| POST | `/api/matches/{id}/stop` | 终止进行中的对局（幂等；对局不存在 404） |
| GET | `/api/catalog/boards` | 板子预设（当前只有 `p9-standard`） |
| GET | `/api/catalog/personas` | 选手档案 |
| GET | `/api/catalog/providers` | 接入预设（脱敏：不含 api_key_env） |

## POST /api/matches 请求体

```json
{
  "game_type": "werewolf",
  "board": { "id": "p9-standard" },
  "seats": [
    { "seat": 1, "persona_id": "calm-analyst", "provider_ref": "mimo/mimo-flash" },
    { "seat": 2, "persona_id": "aggressive-liar", "model": "mock" }
  ]
}
```

- `seats` 必须恰好 `player_count` 条，且 `seat` 恰好是 `1..N` 且不重复（否则 422）。
- 座位接入三选一（优先级从高到低）：
  1. `provider_ref`：`"provider_id"` 或 `"provider_id/model_id"`，从 providers.json 展开
     base_url/api_key_env/model/单价（推荐）；
  2. 显式 `base_url` + `api_key_env` + `model`——`base_url` **必须与 providers.json 中某条一致**，
     否则 422（防止把真实 key 发到任意地址）；
  3. 都不给：用 persona 的 provider/model 绑定；persona 未绑定则回落 `mock`（启发式假 LLM，零网络）。
- 真实接入（非 mock）必须能在环境变量中解析到非空 key，否则 422。
- 未知 `persona_id` / 未知 `provider_ref` / 未知板子 id 一律 422（不静默回落）。
- `board` 可用预设 id（`p9-standard`）或显式 `{"roles": {…}}`（必须等于 standard-9 固定组合）。
- 校验通过即生成 `rng_seed`，落库并异步启动 MatchRunner；事件流首条是 `match.created`。
- 请求体中的座位接入与 persona（style/strategy）**在创建时固化为快照**，改配置不影响历史对局。

## SSE 帧格式

```
id: 42
event: game_event
data: {"seq": 42, "type": "player.speech", "day_index": 2, "phase": "day_speech", "payload": {...}, "vis": {"level": "public", "seats": []}}
```

- `id: <seq>` 即游标；断线重连以 `last_event_id` 查询参数（或 `Last-Event-ID` 头）先补发后订阅。
- `data.vis` 为可见性元数据：服务端已按 `view` 过滤，客户端本地切视角时按 `vis.level` 二次过滤，无需重连。
- `view=immersive` 只发 public；`view=god` 全发（含 seat/god 级）。
- 对局结束发 `event: match_finished`（TUI 收到后停止重连）。

## 鉴权（可选）

默认无鉴权（本机观赛工具）。设置环境变量 `WHOISSPY_API_TOKEN` 后，所有请求必须携带
`X-API-Token: <token>` 或 `Authorization: Bearer <token>`，否则 401。
CORS 允许来源默认只放行本机常见端口，可用 `WHOISSPY_CORS_ORIGINS`（逗号分隔）覆盖。
