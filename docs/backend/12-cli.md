# 12 CLI 入口（main.py）

```bash
python -m app.main [选项]          # 在 backend/ 目录下运行
```

| 参数 | 缺省 | 说明 |
|---|---|---|
| `--mock` / `--real` | `--mock` | 模式；`--real` 走 providers.json + .env |
| `--seed N` | 当前时间（打印） | 随机种子：发牌/平票决胜/定序/模型分配共用 |
| `--db PATH` | `backend/data/whoisspy.db` | SQLite 路径 |
| `--out PATH` | `exports/match-<id>-god.json` | 导出文件 |
| `--view god\|public\|both` | `both` | 导出视角；缺省双视角文件 + 索引（`--out` 单文件时回落 `god`，见第四节） |
| `--trace DIR` | 关闭 | 开启调用留痕（[08-llm.md](08-llm.md)） |
| `--model M` | — | real 模式：模型分配池收窄为单个模型 |
| `--max-days N` | 8 | 天数上限覆盖 |
| `--wolf-rounds N` | 2 | 狼队夜聊轮数覆盖 |
| `--max-calls N` | 600 | 单局调用数护栏 |

## 一、执行序

1. 加载配置（providers/personas/.env；real 模式做 key 预检，缺 key 立即失败退出）；
2. 建库、落 match + 座位快照，打印**模型分配清单**（座位/人设/模型/依据）；
3. `run_match`：逐事件 stdout 直播（present 投影）；
4. 收尾：打印**结果**（胜负与原因）与**用量汇总**（calls/tokens/cost/命中率/兜底数）；
5. 导出 JSON 到 `--out`；关闭 DB。

## 二、stdout 形态（人盯流程的调试面）

```
模型分配：
  1号 aggressive-liar -> mimo-v2.6-pro (persona_binding)
  2号 calm-analyst    -> mimo-v2.6-flash (random)
—— 入夜（第 1 天）——
发牌：1 号 = wolf
发牌：2 号 = seer
……
狼队选择击杀 5 号
第 1 夜：5 号死亡
🏁 对局结束：好人阵营获胜（狼人全部出局）
用量：97 次调用 / 812k tokens / ¥0.61（缓存命中 62%）/ 兜底 3 次
导出：exports/match-1-god.json
```

## 三、退出码与中断

| 情形 | 退出码 |
|---|---|
| 分出胜负（finished） | 0 |
| 手动终止（Ctrl+C）/ 护栏触发 / 流程异常（stopped） | 2 |
| 配置/预检失败 | 3 |

Ctrl+C：捕获后落 `match.stopped {reason: 手动终止}` → 照常导出与用量汇总再退出
（`try/finally` 保证 DB 关闭）；再次 Ctrl+C 强退。

## 四、导出 v2（**已实施**）

前端展示框架（[../frontend.md](../frontend.md)）需要每局**双视角两份文件 + 对局索引**，
CLI 导出行为按 [11-export.md](11-export.md) 第五节调整：

- `--view god|public|both`，缺省 **`both`**；
- 不传 `--out`（缺省）：写入导出目录 `exports/`——`match-<id>-god.json`、
  `match-<id>-public.json` 两份，并合并更新 `exports/index.json`；
- 显式 `--out PATH`：保持旧行为——单文件精确路径（`--view` 生效，单视角），**不更新**
  索引（归档/管道用途）；
- stdout 收尾行相应变为：`导出：exports/match-1-god.json、exports/match-1-public.json + index.json`。
