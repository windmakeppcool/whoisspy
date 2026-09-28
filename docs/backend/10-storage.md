# 10 存储（store.py，裸 aiosqlite）

单进程单写者：一次进程跑一局，事件写入只有 flow 的 emit 一条路径。
因此 **seq 不需要 DB 原子 CAS**——`seq = current_seq + 1` 在代码里分配，
`UNIQUE(match_id, seq)` 作不变量兜底（撞唯一约束=流程 bug，立即暴露而非静默）。

## 一、DDL（幂等，`CREATE TABLE IF NOT EXISTS`）

```sql
CREATE TABLE IF NOT EXISTS match (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  seed INTEGER NOT NULL,
  board_json TEXT NOT NULL,          -- {roles, wolf_meeting_rounds, max_days, model_assignments}
  status TEXT NOT NULL,              -- running | finished | stopped
  result_json TEXT,                  -- {winner, reason}
  current_seq INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS match_seat (
  match_id INTEGER NOT NULL, seat INTEGER NOT NULL,
  persona_id TEXT NOT NULL, style TEXT NOT NULL, strategy TEXT NOT NULL,
  provider_id TEXT NOT NULL, base_url TEXT NOT NULL, api_key_env TEXT NOT NULL, model TEXT NOT NULL,
  price_per_mtok_in REAL NOT NULL DEFAULT 0, price_per_mtok_out REAL NOT NULL DEFAULT 0,
  price_per_mtok_cached_in REAL,
  role TEXT,                          -- 发牌后回填
  PRIMARY KEY (match_id, seat)
);

CREATE TABLE IF NOT EXISTS game_event (
  match_id INTEGER NOT NULL, seq INTEGER NOT NULL,
  type TEXT NOT NULL, day_index INTEGER NOT NULL, phase TEXT NOT NULL,
  payload_json TEXT NOT NULL, vis_level TEXT NOT NULL, vis_seats_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (match_id, seq)
);

CREATE TABLE IF NOT EXISTS llm_call (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  match_id INTEGER NOT NULL, seat INTEGER NOT NULL, purpose TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_tokens INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0,
  cached_prompt_tokens INTEGER NOT NULL DEFAULT 0,
  cost_micros INTEGER NOT NULL DEFAULT 0,
  latency_ms INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,               -- ok | fallback | error
  created_at TEXT NOT NULL
);
```

要点：

- **不含 key 本体**（`api_key_env` 只是变量名）；
- `game_event` append-only，无 UPDATE/DELETE；
- 旧库（SQLModel 时代的 whoisspy.db）**不做迁移**：新代码直接换新库文件（见 [14-migration.md](14-migration.md)）。

## 二、store 函数集

| 函数 | 行为 |
|---|---|
| `init(db_path)` | 建库建表（幂等），返回连接 |
| `create_match(seed, board, seats)` | 插 match + match_seat 快照，返回 match_id |
| `append_event(match_id, event)` | seq 由调用方（emit）分配好，INSERT |
| `add_llm_call(...)` | 每次网关尝试一行 |
| `set_seat_roles(match_id, roles)` | 发牌回填 role |
| `finalize_match(match_id, status, result)` | 收尾更新 |
| `load_events(match_id)` | 按 seq 升序读全量（导出/折叠复算用） |
| `load_match(match_id)` / `load_seats(match_id)` | 元信息 |
| `usage_summary(match_id)` | 汇总 calls/tokens/cost（含 cache_hit_rate） |

全部为 async；写路径不吞异常（迁移诊断类问题在 headless 下不存在——没有旧库要兼容）。

## 三、事务边界

- 每条事件/每行 llm_call 独立提交（append-only 流，崩了已落部分完整可读）；
- `finalize_match` 与最后一条事件之间无原子性要求（match.stopped/finished 本身就是事件）。
