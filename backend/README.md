# whoisspy 后端

FastAPI + SQLite + LLM 网关 + 狼人杀引擎。设计文档在 [`../docs/`](../docs/)（细节以文档为准），本文只讲**怎么跑起来**。

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

配置文件放 `data/`（已被 .gitignore 忽略，缺文件自动回落内置默认，不配也能跑 mock）：

| 文件 | 作用 | 何时必须 |
|---|---|---|
| `data/providers.json` | LLM 接入预设（base_url / api_key_env / 模型池） | 真实 LLM 跑局 |
| `data/personas.json` | 选手人设（style/strategy + 可选 provider/model 绑定） | 想自定义人设时 |
| `data/boards.json` | 板子预设 | 想覆盖内置板子时 |
| `app/config/.env` | `BASE_URL` / `API_KEY` / `MODEL` 等环境变量 | **真实 LLM 必需**（key 只存这里，不进配置/不落库） |

配置格式与校验规则见 [docs/configuration.md](../docs/configuration.md)；坏 JSON / 非法绑定会**拒绝启动**。

## 启动方式

以下命令除特别说明外，均在 `backend/` 目录执行。

### 1. API 服务（Web 前端 / HTTP 客户端用）

```bash
python -m app.main                # 默认 127.0.0.1:8000
python -m app.main --port 9000    # 自定义端口
```

等价写法：`uvicorn app.main:app --host 127.0.0.1 --port 8000`。

API 契约见 [docs/api.md](../docs/api.md)。创建对局时座位可全 `model=mock`（零网络），或指定 provider/model 走真实 LLM。

### 2. TUI 观看器（终端边跑边追更）

```bash
python -m app.main --tui                    # 自动创建一局 mock 对局并进入观看
python -m app.main --tui --real             # 自动创建一局真实 LLM 对局（需 .env + providers）
python -m app.main --tui --real --board p9-standard   # 真实 LLM 标准 9 人局
python -m app.main --tui --board p12-standard         # 指定板子（mock/real 均可）
python -m app.main --tui --match-id 13      # 观看指定对局（复盘历史）
python -m app.main --tui --port 9000        # 后端端口
```

`--board` 可选 `p6-classic`（默认）/ `p8-classic` / `p10-no-seer` / `p9-standard` / `p12-standard`，座位数按板子自动构建。

同一进程内先后拉起 API 与终端视图，与 Web 前端共用同一套 REST/SSE。按键：`q` 退出，`g` 切换上帝/沉浸视角（D16）。

> 提示：真实对局会先打印「模型分配」清单（D19：绑定/随机来源），分配记录随对局落库可查。

### 3. CLI 跑一局（不启服务，直接落库出结果）

**mock 确定性整局**（零网络、调试用）：

```bash
python scripts/run_match.py --mock --board p6-classic --seed 42
```

**真实 LLM 整局**（读 `data/` 配置 + `.env`，按 persona 绑定/池内随机分配模型）：

```bash
python scripts/e2e_real.py                              # 默认 p6-classic
python scripts/e2e_real.py --board p9-standard          # 标准 9 人局
python scripts/e2e_real.py --provider mimo --model mimo-v2.6-pro   # 收窄随机池
```

输出胜负、事件数、token 用量与每座位模型分配记录。板子可选值见 `data/boards.json` / 内置预设（`p6-classic` `p8-classic` `p10-no-seer` `p9-standard` `p12-standard`）。

### 4. 跑测试

```bash
python -m pytest tests/ -q           # 全量（194 个）
python -m pytest tests/test_sheriff_flow.py -q   # 单文件
```

TDD 是项目铁律（见根 CLAUDE.md），改代码前先写失败测试。

## 常见组合

```bash
# 只想看看效果：mock 局 + TUI
python -m app.main --tui

# 真实对局 + 终端观看（需配好 .env 与 providers.json）
python -m app.main --tui --real
python -m app.main --tui --real --board p9-standard   # 标准 9 人局

# 跑一局 9 人标准局并拿结果做复盘
python scripts/e2e_real.py --board p9-standard
python -m app.main --tui --match-id <上一步输出的 match_id>

# 导出某局发言 JSON（上帝视角整局对话：发言/遗言/独白/狼队密聊 + 夜晚操作，离线复盘用）
curl -o match-13-dialog.json http://127.0.0.1:8000/api/matches/13/export
# 端点 GET /api/matches/{id}/export，响应头 Content-Disposition 提示保存为 match-<id>-dialog.json

# 不想记 match_id？CLI 直连库导出最近一局（需后端已跑过并落库，无需服务在跑）：
python scripts/export_dialog.py                         # 最近一局 → match-<id>-dialog.json
python scripts/export_dialog.py --match-id 13           # 指定对局
python scripts/export_dialog.py --match-id 13 --out out.json   # 指定输出文件
```

## 更多文档

| 想了解 | 看这里 |
|---|---|
| 架构与设计支柱 | [docs/architecture.md](../docs/architecture.md) |
| 配置文件格式与密钥安全 | [docs/configuration.md](../docs/configuration.md) |
| 引擎 / 容错链 | [docs/engine.md](../docs/engine.md) |
| 狼人杀规则与板子 | [docs/games/werewolf.md](../docs/games/werewolf.md) |
| 决策记录（D1~D21） | [docs/decisions.md](../docs/decisions.md) |
