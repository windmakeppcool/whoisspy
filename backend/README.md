# whoisspy 后端

单进程 **headless 对局引擎**（D29）：跑一局标准 9 人狼人杀（mock 或真实 LLM）→
事件全量落 SQLite → 导出对话 JSON。无 HTTP 服务；前端因后端重写暂不可用（代码保留）。

设计文档在 [`../docs/backend/`](../docs/backend/00-overview.md)（00–14 分册，细节以文档为准），本文只讲**怎么跑起来**。

## 前置条件

- Python ≥ 3.11
- 依赖安装（仓库已含 `pyproject.toml`）：

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -e .            # Windows PowerShell；Linux/macOS 用 .venv/bin/python
.venv/Scripts/python -m pip install pytest pytest-asyncio   # 跑测试需要
```

## 配置准备

配置文件放 `data/`（整目录 .gitignore，不配也能跑 mock）：

| 文件 | 作用 | 何时必须 |
|---|---|---|
| `data/providers.json` | LLM 接入预设（base_url / api_key_env / 模型池与单价） | 真实 LLM 跑局 |
| `data/personas.json` | 选手人设（style/strategy + 可选 provider/model 绑定） | 想自定义人设时 |
| `app/.env` | `KEY=VALUE` 环境变量（已有环境变量优先） | **真实 LLM 必需**（key 只存这里，不进配置/不落库/不进 trace） |

配置格式与校验见 [docs/backend/09-config.md](../docs/backend/09-config.md)；
坏 JSON / 非法绑定 / 缺 key 会**拒绝启动**（绝不静默跑出一局全兜底的假局）。
板子是代码常量（standard-9，`rules.py`），**没有 boards.json**（D32）。

> 旧版（SQLModel 时代）的 `data/whoisspy.db` 不兼容：`Store.init` 会检测并报错，
> 请删除或改名留档后重跑。

## 跑一局

以下命令均在 `backend/` 目录执行。Windows 控制台默认 GBK，先设 UTF-8 否则直播行（emoji/中文）会报错：

```powershell
$env:PYTHONIOENCODING = "utf-8"
```

### mock 确定性整局（零网络、默认）

```bash
python -m app.main --mock --seed 42
```

同 seed 事件流**逐字节可复现**（发牌/平票决胜/定序/模型分配共用该种子，P3）。

### 真实 LLM 整局

```bash
python -m app.main --real                    # 按 persona 绑定/池内随机分配模型
python -m app.main --real --model mimo-v2.6-pro   # 随机池收窄为单模型
```

启动时打印「模型分配」清单（D19：persona_binding / random），分配记录随对局落库可查。

### 常用参数

| 参数 | 缺省 | 说明 |
|---|---|---|
| `--seed N` | 当前时间 | 随机种子（发牌/决胜/定序/模型分配） |
| `--out PATH` | `exports/match-<id>-god.json` | 导出对话 JSON（复盘/归档） |
| `--view god\|public` | `god` | 导出视角：god 全量 / public 只公开事件 |
| `--trace DIR` | 关闭 | 调用留痕：每次 LLM 调用的完整 prompt/响应 JSONL（排障用） |
| `--db PATH` | `data/whoisspy.db` | SQLite 路径 |
| `--max-days N` / `--wolf-rounds N` | 8 / 2 | 规则可调项 |
| `--max-calls N` | 600 | 单局调用数护栏（超限 → stopped，退出码 2） |

完整参数与输出形态见 [docs/backend/12-cli.md](../docs/backend/12-cli.md)。

### 输出示例

```
模型分配：全部 mock（--real 接入真实 LLM）
发牌：1 号 = seer
发牌：2 号 = villager
……
—— 入夜（第 1 天）——
6 号（狼队频道）：我是 6 号，kill 环节发言（mock）。
……
🏁 对局结束：好人阵营获胜（狼人全部出局）
用量：81 次调用 / 34007 tokens / ¥0.00（缓存命中 0%） / 兜底 0 次 / 规则异常 0 次
导出：exports\match-1-god.json
```

退出码：`0` 分出胜负 / `2` 被终止（Ctrl+C、调用数超限、流程异常）/ `3` 配置错误。

## 跑测试

```bash
python -m pytest tests/ -q           # 全量（当前 204 passed）
python -m pytest tests/test_rules.py -q   # 单文件
```

TDD 是项目铁律（见根 CLAUDE.md），改代码前先写失败测试；测试策略与验收基线见
[docs/backend/13-testing.md](../docs/backend/13-testing.md)。

## 常见组合

```bash
# 只想看看效果：mock 一局 + 导出 + 留痕
python -m app.main --mock --seed 42 --trace tmp-trace

# 真实对局（需配好 .env 与 providers.json）
python -m app.main --real

# 导出公开视角（不含狼队密聊/独白/夜晚操作）
python -m app.main --mock --seed 42 --view public --out exports/match-public.json

# 翻查上一局（同一库新跑一局会自动 +1 编号）
python -m app.main --mock --seed 1
python -m app.main --mock --seed 2   # match-2；导出 exports\match-2-god.json
```

## 更多文档

| 想了解 | 看这里 |
|---|---|
| 架构总览与设计原则 | [docs/backend/00-overview.md](../docs/backend/00-overview.md) |
| 模块结构与依赖方向 | [docs/backend/01-structure.md](../docs/backend/01-structure.md) |
| 对局流程规格 | [docs/backend/02-flow.md](../docs/backend/02-flow.md) |
| 配置格式与密钥安全 | [docs/backend/09-config.md](../docs/backend/09-config.md) |
| 狼人杀规则书（规则口径） | [docs/games/werewolf.md](../docs/games/werewolf.md) |
| 决策记录（含 D29 重写） | [docs/decisions.md](../docs/decisions.md) |
| 落地记录与偏差 | [docs/backend/14-migration.md](../docs/backend/14-migration.md) |