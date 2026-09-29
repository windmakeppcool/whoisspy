# 前端展示框架（Vue 3 + TypeScript）

> **状态**：**已落地**（静态导出直读复盘，2026-09-29；后端导出 v2 见
> [backend/11-export.md](backend/11-export.md) 第五节）。路线：**静态导出直读**——CLI 跑局
> 产出导出 JSON，前端零服务直接复盘；直播/建局留给最小 API 阶段（[roadmap.md](roadmap.md)）。
> 视觉规范唯一权威在 [frontend-design.md](frontend-design.md)，本册只管结构与数据。

## 一、定位与三条铁律

前端是「**纯渲染器**」：把后端产出的展示文档渲染成一张卡通牌桌，自己不产生任何游戏语义。

1. **不解释事件**（后端 P5 的延伸）：观赛文案（Line）唯一来自后端 `present.py`；前端连
   「第几夜」都不从文案反推——昼夜、存活、警长、票型全部由结构化字段直供
   （见 [backend/11-export.md](backend/11-export.md) 第五节）。
2. **展示契约唯一**：前后端唯一契约 = 导出 JSON v2（下称**展示文档**，schema 权威在
   [backend/11-export.md](backend/11-export.md)）；列表页契约 = `exports/index.json`。
   前端不碰 SQLite、不需要 API。
3. **视角切换 = 换文档**：god / public 是两份导出文件，切换即重新加载另一份。导出是唯一
   出站过滤点（可见性以落库值为准），前端不做二次过滤——沉浸视角下狼队频道/独白/角色徽章
   「自然不存在」（文档里就没有这些行），不靠前端隐藏。

## 二、数据流总览

```
python -m app.main --mock --seed 42          # backend/ 下执行
  → backend/exports/match-1-god.json + match-1-public.json + index.json
  → 前端 MatchSource（静态导出源 / 本地文件源）
  → stores/replay（展示文档 + 视角 + 段落游标）
  → MatchView 复盘舞台（SkyBackdrop / SeatColumn / PhaseBanner / DialogueTheater / VoteDrawer / …）
```

## 三、数据源抽象（source/）

```ts
interface MatchSource {
  list(): Promise<MatchSummary[]>                        // 对局索引（列表页）
  load(matchId: number, view: 'god' | 'public'): Promise<DisplayDoc>   // 展示文档
}
```

| 实现 | 数据来源 | 场景 |
|---|---|---|
| `StaticExportSource` | fetch `<base>/index.json`、`<base>/match-<id>-<view>.json` | dev：Vite 中间件把 `/exports/` 挂到 `../backend/exports`；部署：前端构建产物与 `exports/` 同源静态托管。`base` 由 `VITE_EXPORTS_BASE` 注入 |
| `LocalFileSource` | 拖拽 / 文件选择打开单个导出 JSON | 零部署分享复盘：把导出文件发给任何人，浏览器直接打开渲染 |

- `LocalFileSource` 单文件即单视角：视角按钮禁用并提示「请打开对应视角的文件」（文档自带 `view` 字段）。
- 列表页同时提供「本地打开」入口（无 `index.json` / 空目录时的主路径）。
- 阶段 B 预留 `ApiSource`（REST 回放同 schema + SSE 直播增量帧），接口不变、视图无感（第八节）。

**运行时守卫**：`model/display.ts` 对文档做结构校验；检测到 v1 文档（无 `is_night / stage / votes`）
→ 明确报「请用新版 CLI 重新导出」，**绝不静默降级**、绝不前端补算。

## 四、路由与页面

| 路由 | 页面 | 数据 | 变化 |
|---|---|---|---|
| `/` | MatchListView | `index.json` | 改造：卡片列（编号/胜负/种子/人数/导出时间/可用视角）+「本地打开」入口；「创建对局」按钮移除（阶段 B 恢复） |
| `/matches/:id` | MatchView（复盘舞台） | `match-<id>-<view>.json` | 改造：数据层换 `MatchSource`；`?view=god\|public` 深链可分享 |
| `/matches/local` | MatchView（本地文件态） | `LocalFileSource` | 新增 |
| `/create` | — | — | 暂下线（无 API 无建局） |

视角切换：顶栏按钮（快捷键 `G` 沿用）→ store 换 `view` 重新 `load` → 全量重渲染。

## 五、复盘舞台：文档 → 组件

页面结构沿用设计稿三栏（座位列 ｜ 中央剧场 ｜ 座位列 + 顶栏 + 段落导航条），布局与视觉
一律以 [frontend-design.md](frontend-design.md) 为准。

| 文档字段 | 组件 | 投影 |
|---|---|---|
| `segment.is_night / day_index / label` | `SkyBackdrop` · `PhaseBanner` | 昼夜天光 2.4s 过渡（签名元素）；木牌「第 N 夜/天」 |
| `match.seats` + `segment.stage.{alive, sheriff}` | `SeatColumn` / `SeatCard` | 死亡✖、警长🏅、（仅 god 文档）角色徽章+阵营边条；沉浸视角中性 |
| `segment.entries[].kind` | `DialogueTheater` | 见下表 |
| `segment.votes[]` | `VoteDrawer` | 该段投票回合：末回合展开、历史回合折叠；条宽按最高票归一 |
| `match.winner / reason` | 终局横幅（剧场尾行 + `MatchView` 顶部横幅） | 🏁 胜负与原因。**保留悬念**：横幅仅在进度抵达末段（`currentSegment === segments.length - 1`）时显示，前段复盘不剧透 |
| `usage` | `UsagePanel`（新增小组件） | 调用数 / tokens / 费用 / 缓存命中率 / 兜底数 / 规则异常数 |

Line kind → 剧场形态：

| kind | 形态 |
|---|---|
| `speech` / `last_words` | 左右交替白底气泡（按座位 side）；遗言挂灰标签 |
| `channel` | 狼队频道粉色居中气泡（仅 god 文档存在） |
| `monologue` | 紧随同座 `speech`/`last_words`/`channel` 时**折叠进该气泡**（虚线分隔 +「内心」标签，`mergeMonologues` 纯函数只折叠结构、不改文本）；独立动作内心（查验/投票/用药等无前置发言者）保留虚线小卡。仅 god 文档存在 |
| `system` | 居中胶囊旁白 |
| `phase` | 段内弱化分隔行 |
| `vote` | 「X 号投票给 Y 号」计入旁白流（结构化票型在 VoteDrawer） |

**「当前段」驱动状态**：剧场整卷滚动 + IntersectionObserver 判定视口所在段；天空 / 木牌 /
座位列 / 投票抽屉全部取**该段的 `stage` / `votes`**——段快照让「任意前缀渲染」零成本，
是时间轴拖拽（roadmap 暂缓项）的天然地基。发言中座位弹起 = 当前视口最后一条
`speech / channel / last_words` 的 seat（纯视觉派生，允许）。

**段落导航**：`DirectorBar` 从设计稿工具**转正**为复盘导航——章节胶囊 = `segments`，
‹ › 切换、点击滚到段；顶部细进度条（`role="progressbar"`，宽度 = `(当前段+1)/总段数`）+
「N / M」当前段数字强化进度感。自动播放/倍速暂缓（roadmap 不变）。

**换文档必须重置滚动**：`DialogueTheater` 的组件实例在视角切换时被 Vue 复用，
`watch(segments)` 里必须显式 `scrollTop = 0` 再重挂 IntersectionObserver——否则旧滚动位置
会被 observer 当成新文档的当前段回写，导致进度条/木牌与内容错位（此 bug 已修，见第十节）。

**加载态**：`store.loading` 期间渲染居中旋转圈 + 「正在加载对局……」，并**卸载**舞台与
`DirectorBar`（`v-if="store.doc && !store.loading"`）——避免换视角时旧文档的进度条/内容闪现。

## 六、状态管理与退役清单

Pinia：

- `stores/replay.ts`（新）：展示文档、`view`、当前段游标（滚动驱动）、`load(view)` 换文档、终局态。
- `stores/matchList.ts`（重写）：`Source.list()`。

退役（后端重写后已成死代码或 P5 违例，实施时删除）：

| 删除 | 理由 |
|---|---|
| `api/client.ts` · `api/sse.ts` | 旧 FastAPI 契约（服务端已删）；阶段 B 按新契约重写 |
| `model/project.ts` + `project.test.ts` | 前端自带事件解释，P5 违例（这正是 D29 根治的漂移病灶） |
| `stores/match.ts` · `stores/catalog.ts` | 旧 API 时代 store；由 replay / matchList 取代 |
| `views/CreateMatchView.vue` | 无 API 无建局；阶段 B 恢复 |

`mock/match.ts` 保留为组件开发与视觉走查 fixture（不进生产数据路径）。

## 七、测试

- vitest 纯函数：display 守卫（合法 v2 / 坏文档 / v1 拒绝）、段落游标推进、VoteDrawer 票数归一、
  `mergeMonologues` 内心折叠（发言/频道/遗言各态、不同座不合并、条数守恒）；
- 组件冒烟：MatchView 以真实导出文件（`backend/exports/match-*-god.json`）为 fixture；
- 契约由后端锁死：`test_export` 覆盖 v2 字段（[backend/13-testing.md](backend/13-testing.md)）。

## 八、演进：阶段 B 最小 API（只画边界，不展开）

[roadmap.md](roadmap.md) 既定方向。**同一契约的增量形态**，前端只换 `ApiSource` 即接入：

- REST：`GET /api/matches`（= `index.json`）、`GET /api/matches/:id?view=`（= 展示文档）；
- SSE 直播帧 = 展示文档的增量分解：`segment_open / line / segment_close(stage, votes) / usage / finished`
  ——复盘（整文档）与直播（帧流 append 进同一文档模型）同构，「观赛/复盘共用组件」由此达成；
- 建局 `POST /api/matches`；
- 启动时另立 API 规格文档，不复活旧 `api/app.py`。

## 九、设计决策记录

（决策记录文档 `decisions.md` 已删除；前端域决策记于本节，编号 F 系）

| # | 决策 | 取舍 |
|---|---|---|
| F1 | 静态导出直读先行，API 留阶段 B | 复盘零服务即可用；只有建局/直播才需要 HTTP |
| F2 | 展示契约 = 导出 JSON v2 超集，而非前端事件 reducer | P5 投影单一归属；根治四份投影漂移的旧病灶 |
| F3 | 段末 `stage` 快照由后端 export 复用 `state.apply` 折算 | 无新解释逻辑；reducer 已被折叠一致性测试锁死 |
| F4 | 视角切换 = 换文档 | 导出是唯一出站过滤点；响应体中无视角外数据 |
| F5 | `DirectorBar` 转正为段落导航 | 段快照使「按前缀渲染」零成本 |
| F6 | `index.json` 由 CLI 导出时维护 | 静态可部署可归档；前端不扫目录、后端不起服务 |

## 十、落地记录（已实施 2026-09-29）

按本册设计全部落地，验收如下：

1. 后端：export v2（`is_night / stage / votes / persona_name`）+ `index.json` + `--view both`
   缺省双视角（规格 [backend/11-export.md](backend/11-export.md) 五；测试 `test_export` 增补）；
2. 前端：`model/display.ts` 守卫 + `model/replay.ts` 纯投影 + `source/` 静态/本地文件源 +
   `stores/replay` 重写（vitest 16 用例全绿）；
3. 前端：MatchListView / MatchView 复盘舞台接入（DirectorBar 段落导航、UsagePanel、
   视角切换=换文档、本地文件打开），旧 `api/` `model/project.ts` `stores/match|catalog` 退役删除；
4. 验收：后端全量测试绿（212 passed + 1 个环境相关用例）；前端 `vitest` 16 通过、
   `vue-tsc -b && vite build` 通过；`python -m app.main --mock --seed 42` 产出
   `exports/match-3-{god,public}.json + index.json`，dev server `/exports/` 读取正常。

### 补充：显示逻辑优化（2026-09-29 二轮）

1. **修复**「换视角后当前段错乱」：`DialogueTheater` 换文档时未重置 `scrollTop`，
   IntersectionObserver 用旧位置回写 `currentSegment` → 进度条/木牌错位。
   修法：`watch(segments)` 内 `scrollTop = 0` 后重挂 observer（新增不变量，见第五节）；
2. 内心合并：新增纯函数 `mergeMonologues`（TDD 7 用例），发言/遗言/狼队频道气泡内折叠
   紧随同座内心（虚线分隔 +「内心」标签），独立动作内心保留虚线小卡；
3. 进度条：`DirectorBar` 增顶部细进度条 + 「N / M」当前段数字；类名用 `progress-track`
   以避开 `VoteDrawer` 的 `.track`（投票条）歧义；
4. 悬念：终局横幅只在末段揭示胜负；加载态居中旋转圈并卸载舞台与进度条。

验收：`vitest` 23 通过（3 文件）、`vue-tsc -b` 通过、`vite build` 通过；浏览器实测
视角切换双向 `god ↔ public` 均归零至 `1 / 7`，加载态与终局揭示时点符合预期；控制台仅
favicon 404。

