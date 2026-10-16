# 15 常驻对局服务（serve 模式）协议规格

> PC 游戏方案（[pc-game.md](../pc-game.md) 第二、三节，D34/D35）的 sidecar 通信契约。
> 本文是 **serve 模式的唯一协议规格**；引擎内核仍以 00-overview 为准，
> 展示文档契约以 [11-export.md](11-export.md) 第五节为准（直播帧是其增量分解）。
> 不复活旧 `api/app.py`（见 [14-migration.md](14-migration.md) 第三节）。

## 一、启动与传输

```bash
python -m app.main --serve --token <t> [--seed N] [--db PATH] [--real]
```

- `--serve`：常驻模式（12-cli 新增；与既有 CLI 路径互斥，其余选项语义不变）；
- 端口自选（`0` → 系统分配），**仅绑定回环** `127.0.0.1`；实际端口回打进
  **stdout 首行**（一行纯数字），Electron main 读取后注入 renderer；
- **握手 token**：Electron main 生成随机 token 作为 `--token` 启动参数；
  每个连接的首帧必须是 `hello {token}`，不匹配立即断开。token 不落日志、
  不入库（与密钥同口径，CLAUDE.md 规则 4）；
- 消息一律 UTF-8 JSON 文本帧；单客户端假设（单机单窗口），无会话管理；
  断线后客户端重连 → `sync` 取当前前缀全量快照，再续接增量帧。

## 二、消息族

**客户端 → 引擎**（请求）：

| 消息 | 说明 |
|---|---|
| `hello {token}` | 握手（连接首帧必发；token 不匹配立即断开；校验通过回 `ok`） |
| `create {game, board, seed?, seats, paused?}` | 建局：`game`（当前 `"werewolf"`）、`board`（空对象 = 默认板子 standard-9）、`seats=[{seat, type}]`（`type: "llm"`；档 2 加 `"human"`）、`paused: true` 开局即暂停（等客户端手动播放） |
| `pace {op, value?}` | 节奏控制：`op: pause / resume / frame / speed`，`speed` 带 `value`（每帧投递间隔秒数，0 = 立即，缺省 0） |
| `sync` | 请求当前前缀全量快照（断线恢复/窗口重开） |
| `list` | 对局索引（含 running；条目同 `index.json`） |
| `export {match_id}` | 触发双视角导出 + 更新 `exports/index.json`（复用 CLI 收尾逻辑） |
| `action {...}` | 人类座位动作（档 2 实现，协议占位） |

**引擎 → 客户端**（推送帧；`create` 应答后开始推流，帧序与事件序严格一致）：

| 帧 | 说明 |
|---|---|
| `ok {match_id?}` / `error {message}` | 请求应答（`create` 应答带 `match_id`；`sync` 应答是 `snapshot`） |
| `match_open {match}` | 开局元信息 = 展示文档 `match` 字段（seed/status/board/seats/model_assignments；`view` 恒 `god`） |
| `seat_role {seat, role}` | 发牌结果（`role.dealt` 的 god 化投影，直播新增帧：刷新 `match.seats[].role`，不进展示文档段） |
| `segment_open {label, day_index, is_night}` | 段开始（展示文档段字段子集） |
| `line {kind, seat, text}` | 观赛行（`present` 投影；`kind` 同展示文档 `entries[].kind`） |
| `segment_close {stage, votes}` | 段结束（`stage: {alive, sheriff}` 快照 + 段内结构化投票回合，与展示文档段同构） |
| `usage {…}` | 终局用量（= 展示文档 `usage` 字段，`finished/stopped` 之前推） |
| `finished {winner, reason}` | 分出胜负（结构化，对应 `match.finished`） |
| `stopped {reason}` | 对局终止（对应 `match.stopped`） |
| `snapshot {doc}` | `sync` 应答：当前前缀完整展示文档（`view: "god"`） |

帧 = [export.py](../app/export.py) 分段逻辑的**增量分解**：同一分段键、同一可见性过滤、
同一 `present` 投影、段末 `stage` 同一折叠口径（对全量事件折叠，含视角外事件）。
协议不新增事件解释逻辑（P5）。

## 三、节奏控制（pc-game 4.4）

- `pace pause`：flow 在 **ask 入口**与**阶段边界**（`phase()`）处 `await` 暂停点；
  暂停期间不发起 LLM 调用；`pace resume` 解除；
- `pace frame`：暂停态下放行**一个观众原子**（一个事件 → 其产出的帧推送完毕），
  用于逐帧观赛；非暂停态忽略；
- `pace speed {value}`：帧投递间隔秒数（0 = 立即，缺省 0）。只作用于投递侧，
  引擎照常跑；
- 确定性（P3）不受影响：节奏只 gate 执行时机，不进随机源。

## 四、与展示文档的关系

- `sync` 快照与增量帧**同构**：快照 = `build_export` 当前前缀；随后增量帧 append
  进同一 DisplayDoc 模型（frontend.md 第八节）；
- 复盘（整文档）与直播（帧流）共用组件；`seat_role` 是唯一不进展示文档段的帧；
- `list` 的 running 条目状态为 `"running"`、`views` 为空数组（无导出文件）。

## 五、实施分期对应

- 档 1（观战闭环）：本册全部 + 全 `llm` 座位 + 节奏控制；
- 档 2（入座对战）：`seats[].type: "human"` + `action` + `input_required` 帧 +
  托管兜底（pc-game 4.2/4.3，实施时追加小节）；
- 档 3：`game` 字段贯通（D36，实施时追加）。