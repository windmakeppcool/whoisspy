# PC 游戏架构（Electron 客户端 + Python sidecar 引擎）

> 决策依据：[decisions.md](decisions.md) **D34–D37**（产品形态转纯 PC 游戏 / 双进程架构 /
> 多游戏成册分目录 / Steam 专项裁剪）。本文是 PC 化的**唯一架构规格**；
> 引擎内核规格仍以 [backend/00-overview.md](backend/00-overview.md) 为准，
> 展示组件与直播帧契约仍以 [frontend.md](frontend.md) 为准。

## 一、定位与范围

产品形态 = **纯 PC 单机游戏**（D34）：

- **入座模式**：人占一个（或多个）座位，与 LLM 玩家同桌打狼人杀；
- **观战模式**：入座人数为零的**退化形态**——同一代码路径，只是所有座位都走 LLM 分支；
- 对手保持 LLM 驱动（多人设/多模型混战，D5 不变）；
- 节奏控制（暂停/倍速/逐帧）是必备能力，不再是 roadmap 暂缓项；
- 导出/静态复盘能力**保留**，作为离线回放与分享路径。

**明确不做**（D37）：Steamworks 集成（云存档/成就/Deck Verified）、联网多人、
成就事件观察者。

## 二、总体拓扑：双进程

```
┌─────────────────────────────┐        本机回环 WebSocket           ┌──────────────────────────┐
│ Electron 客户端（主进程）      │  ws://127.0.0.1:<port>?token=…   │ Python 引擎 sidecar       │
│  ├ renderer: frontend/ Vue  │ ◄──────────────────────────────► │  ├ 常驻对局服务（新 CLI 模式）│
│  │   （复盘舞台 + 直播帧消费）  │   启动握手 token + 帧协议          │  ├ flow.py 直排对局        │
│  └ main: 窗口/sidecar 管理    │                                  │  └ SQLite + exports       │
└─────────────────────────────┘                                  └──────────────────────────┘
```

- **Electron 主进程**负责：窗口生命周期、spawn/监督 sidecar（PyInstaller 单目录产物）、
  生成一次性握手 token、把 token 与端口注入 renderer。
- **Python sidecar** 负责：加载配置 → 建局 → 跑对局 → 落事件 → 推直播帧 → 收尾导出。
  引擎保持无 UI 依赖，`python -m app.main` 仍是独立可跑的调试入口（12-cli.md 不变）。
- **崩溃隔离**：renderer 崩 = 重开窗口（对局在 sidecar 继续）；sidecar 崩 = 客户端提示
  「对局异常终止」，事件流已落库，可按回放路径查看残局。
- 打包：PyInstaller `--onedir` 打包 `backend/`，Electron `extraResources` 携带；
  与 renderer 的相对路径由 Electron main 层封装。

**否决的备选**（D35）：pywebview 进程内桥（生态与 Overlay 余地不如 Electron）、
Godot/Unity 壳（重写 Python 资产；留作将来表现力升级的备选内核——届时引擎与通信契约不动）、
单进程合并（崩溃隔离与打包边界不清晰）。

## 三、通信契约

### 3.1 传输

- `ws://127.0.0.1:<动态端口>`，**仅绑定回环**；端口由 sidecar 启动时自选（0 → 实际端口
  回打进 stdout 首行，Electron main 读取）。
- **握手 token**：Electron main 生成随机 token 作为 sidecar 启动参数
  （`--serve --token <t>`），每条 WS 消息首帧须携带校验；不匹配立即断开。
  token 不落日志、不入库（与密钥同口径，CLAUDE.md 规则 4）。
- 单客户端假设（单机单窗口），不做重连协商以外的会话管理：断线后客户端可发
  `sync` 请求取当前对局全量快照（= 展示文档当前前缀），再续接增量帧。

### 3.2 消息族

**客户端 → 引擎**（请求）：

| 消息 | 说明 |
|---|---|
| `create {game, board, seed?, seats}` | 建局：选游戏 + 选板子 + 每座位 `human / llm` |
| `action {...}` | 人类座位动作（发言/投票/技能/过），对应当前 `ask` 的 action 协议 |
| `pace {op: pause/resume/speed/frame}` | 节奏控制（见第四节） |
| `sync` | 请求全量快照（断线恢复/窗口重开） |
| `list` / `export {match_id}` | 对局索引 / 触发导出 |

**引擎 → 客户端**（推送，直播帧）：

沿用 [frontend.md](frontend.md) 第八节**同一契约**（复盘整文档与直播帧流同构）：

```
segment_open / line / segment_close(stage, votes) / usage / finished
```

- 帧 = 展示文档的增量分解；renderer 用 `ApiSource`（frontend.md 第三节预留位）
  把帧 append 进与静态导出**同一 DisplayDoc 模型**，观赛/复盘/直播共用组件；
- 展示文档与帧加 `game` 标识（D36），前端按游戏渲染对应桌面；
- `ask` 轮到人类座位时，引擎额外推一帧 `input_required {seat, spec 摘要, deadline}`
  作为「该你行动」的驱动信号（不进展示文档，只做 UI 状态）。

启动时另立**协议规格小节**（追加到本文或新建 `docs/backend/15-serve.md`），
不复活旧 `api/app.py`。

## 四、引擎侧改动

全部落在 `backend/app`，遵守既有设计原则（P1–P6）与模块边界（CLAUDE.md 规则 6）。

### 4.1 常驻对局服务（CLI 扩展，非新框架）

`main.py` 加 `--serve` 模式：起 WS 监听 → 收 `create` → `run_match` → 对局期间持续推帧。
复用现有执行序（12-cli.md）：配置加载、建库落 match、模型分配清单、收尾导出与用量汇总
一律不变；**非 serve 的 CLI 路径零改动**。

### 4.2 人类座位：`flow.ask/speak` 显式分支

```python
# flow.py（示意）
async def ask(self, seat_no, spec, purpose, ...):
    if self.seats[seat_no].get("seat_type") == "human":
        return await self._ask_human(seat_no, spec)   # 等客户端 action 帧
    ...                                              # 现有 agent_ask 管线不变
```

- **不引回 Driver/注册表抽象**（P1 直排铁律）：就是一处 `if`，人类回复构造成与
  `AgentReply` 同构的结果，后续校验/兜底/monologue 落库路径与 LLM 座位**完全共用**；
- 人类座位的 `monologue` 为空 → 不落 `player.monologue`（07-agent.md 语义顺延）；
- 事件流中人类动作与 AI 动作**同构**（同事件类型、同可见性），回放/导出零特判。

### 4.3 托管（超时兜底）

人类座位在 `deadline` 内未收到 `action` → 按 07-agent.md 的**中性动作**兜底
（绝不替玩家用药/开枪，D25），事件记 `auto_taken` 类标记供 UI 提示「已托管」；
玩家随时可发 `action` 结束托管后的回合则不可用（回合已过，与 AI 兜底同语义）。

### 4.4 节奏控制

- `pause/resume`：flow 在阶段边界与 `ask` 入口处 `await` 一个 `pace_event`
  （显式 if，不是拦截器）；`speed` 只作用于客户端渲染与帧投递间隔，引擎照常跑；
- `frame`（逐帧）：暂停态下每发一次前进指令推进一个「观众原子」
  （一段 segment 或一条 line）；
- mock 模式确定性（P3）不受影响：节奏只 gate 执行时机，不进随机源。

### 4.5 观战 = 零人类座位

`create` 里全部座位 `llm` 即纯观战局；客户端 UI 上「入座/观战」只是建局时座位分配的
两种预设，引擎不区分模式。

## 五、Electron 客户端

- **renderer 直接复用 `frontend/`**（Vue 3 + TS + Pinia + Vite）：复盘舞台、组件、
  视觉规范（[frontend-design.md](frontend-design.md)）零改动接入；
- 新增 `ApiSource` 实现 `MatchSource` 接口（frontend.md 第三节预留）：
  WS 帧流 → DisplayDoc 增量；静态导出/本地文件源保留为回放与分享路径；
- 入座 UI：座位卡上的「入座 / 观战 / 指派 AI」切换、发言输入面板（受 240 字上限约束）、
  节奏控制条（暂停/倍速/逐帧）；
- 设置页：LLM key 输入（见第六节）、provider/persona 选择沿用 `backend/data/` 配置；
- Electron main 层职责保持「薄」：不解释对局语义（P5——游戏语义只在 renderer 的
  展示组件与引擎内）。

## 六、密钥与本地数据（D37）

- **玩家自带 key**：设置界面输入 → 存 **OS 凭据管理器**（Windows DPAPI /
  macOS Keychain，经 Electron `safeStorage` 或系统 keytar 类库）；
- 注入路径不变：sidecar 启动时经环境变量还原 → 仍只走 `api_key_env`
  （不进配置/不落库/不进日志/不进 trace，CLAUDE.md 规则 4 铁律）；
- **本地数据集中单一目录**（云存档余地）：`<userData>/whoisspy/` 下集中放
  `whoisspy.db` + `exports/` + `settings.json`（不含密钥）——将来接云存档 = 同步该目录；
- 现阶段**不接** Steamworks：无 Steamworks SDK、无成就/云存档调用。

## 七、多游戏边界（D36）

- 维持 D32「不预设插件抽象」：不复活 GameDefinition/registry，不抽通用步进；
- **每游戏一册分目录**：`app/<game>/rules|flow|prompts|memory|present`，
  现有狼人杀五模块届时整体移入 `app/werewolf/`（`events/state/store/llm/config`
  保持全局共享，无游戏语义）；
- 加游戏 = 加一册 + 一个直排 flow + 建局配置多一个「选游戏」维度；
- 展示文档/直播帧带 `game` 字段，前端按游戏渲染对应桌面组件；
- 第二个游戏（阿瓦隆等）落地时按实际教训再抽共性，**不提前设计**；
- 板子仍是代码常量（D32），无 boards.json。

## 八、与既有文档的关系

| 文档 | PC 化后的状态 |
|---|---|
| [backend/00-overview.md](backend/00-overview.md) | 内核规格不变；「无 HTTP/WebSocket」非目标收窄为「引擎本体仍无，serve 层是独立薄壳」 |
| [frontend.md](frontend.md) 第八节 | 由本方案接管实现（WS 帧替代 SSE，消息族见 3.2）；`ApiSource` 从「阶段 B 预留」转正 |
| [roadmap.md](roadmap.md) | 「重建最小 API」并入本方案；节奏控制/时间轴从暂缓项转必备/半必备 |
| [backend/12-cli.md](backend/12-cli.md) | 追加 `--serve` 模式（实施时补写） |
| [backend/14-migration.md](backend/14-migration.md) | 历史记录，不改 |

## 九、实施分期

**档 1：观战闭环（最小可玩）**（**已实施** 2026-10-15，协议见 [15-serve.md](backend/15-serve.md)）

1. sidecar `--serve` + WS 握手/token + `create`（全 LLM 座位）；
2. `ApiSource` 接直播帧 → 现有复盘舞台实时演播（观战 = 零人类座位）；
3. 节奏控制 pause/resume/frame；
4. Electron 壳 + sidecar 打包（PyInstaller），跑通「打开客户端 → 建局 → 看完一局」。

**档 2：入座对战**

1. `flow.ask/speak` 人类座位分支 + `action` 帧协议；
2. 托管超时兜底 + `input_required` 驱动的入座 UI（发言/投票面板）；
3. 玩家自带 key（OS 凭据管理器 → `api_key_env`）+ 设置页；
4. 人类入座局的事件流/导出回归测试（与 LLM 局同构断言）。

**档 3：Steam 余地与第二游戏**

1. 本地数据集中目录收口（云存档同步点）；
2. 建局配置「选游戏」维度 + `game` 字段贯通展示文档与前端路由；
3. 第二游戏成册（D36 口径）；
4. Steam 专项启动时再议：Steamworks 接入方式、托管 key/计费、成就观察者
  （事件流天然支持，届时再做）。
