# 后续方向（暂缓项）

只列不设计。某项启动时移入对应文档（或新建 `<feature>.md`）展开设计，并在 [decisions.md](decisions.md) 记录决策。

## 已明确暂缓（访谈收口，D7 相关）

| 项 | 现状留的余地 |
|---|---|
| 播放节奏控制（暂停/倍速） | 事件流带 seq，天然可做游标控制 |
| 时间轴拖拽 | append-only 事件 + Reducer，任意前缀可重建 |
| 分叉重跑 | 随机结果带种子写入事件，可从任意事件前缀换种子续跑 |
| 自定义角色 / 技能 DSL | D3 明确不做；如启动需先修订 [game-plugin.md](game-plugin.md) 契约 |

## 规则与游戏扩展

- 标准完整局档位（预女猎白、警长、自爆、吞刀…）：boards.json 加 `ruleset` 档位（D2）。
- 新游戏插件：谁是卧底、阿瓦隆等（按 [game-plugin.md](game-plugin.md) 接入清单）。
- persona × game 策略矩阵（策略按游戏覆写，D11 备选）。

## 工程扩展

- Postgres / 上云：storage Repository 抽象已留后路（D9）。
- 多房间 / 鉴权 / 多观众视角定制。
- 用量预算告警、成本优化（prompt 缓存、模型路由）。
