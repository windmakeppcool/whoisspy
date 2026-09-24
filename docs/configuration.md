# 配置管理

所有配置文件采用 **JSON**（D13），放 `backend/data/`（整目录 .gitignore，不入库）；加载时用 pydantic 校验，坏配置拒绝启动。API key 只经环境变量注入——**配置里永远只有环境变量名，没有 key 本体**（全局安全规范）。

## providers.json（接入预设库，可选）

```json
{
  "providers": [
    {
      "id": "demo",
      "base_url": "https://api.example.com/v1",
      "api_key_env": "DEMO_API_KEY",
      "currency": "CNY",
      "models": [
        { "id": "model-a", "price_per_mtok_in": 2.0, "price_per_mtok_out": 8.0 }
      ]
    }
  ]
}
```

创建对局时可引用预设，服务端**展开固化**进 match_seat（D10）；也可每座位直接给 base_url/api_key_env/model（+可选单价，缺省用预设或 0）。`GET /api/catalog/providers` 返回时 `api_key_env` 保留字段名但永不返回 key 值。

## personas.json（选手档案，style + strategy，D11）

```json
{
  "personas": [
    {
      "id": "aggressive-liar",
      "name": "悍跳强攻型",
      "style": "语气强硬、短句、爱用反问；被质疑时提高音量重复结论。",
      "strategy": "拿狼必悍跳预言家，首夜就起跳；被围剿时反踩最沉默的人；好人局喜欢带节奏抢归票位。"
    },
    {
      "id": "calm-analyst",
      "name": "冷静盘逻辑型",
      "style": "条理清晰、分点陈述、克制不情绪化。",
      "strategy": "优先盘票型与刀型；信息不足时明说不确定；发现悍跳会用证据链逐步拆解而非对喊。"
    }
  ]
}
```

`style` 决定「怎么说」，`strategy` 决定「做什么」——prompt 分层注入，便于分别调优（详见 [agents-and-llm.md](agents-and-llm.md)）。

### persona 绑定接入（D18：选手卡 = 性格 + 模型）

persona 可选绑定 provider/model；座位未显式指定接入时自动展开，同桌可混搭不同模型：

```json
{
  "id": "vote-analyst",
  "name": "票型数据型",
  "style": "冷静克制……",
  "strategy": "优先盘票型……",
  "provider_id": "mimo",
  "model": "mimo-v2.6-pro"
}
```

- `provider_id` 必须存在于 providers.json，`model` 必须属于该 provider，`model` 不带 `provider_id` 直接拒绝启动（加载时交叉校验）。
- 优先级（D19）：座位显式 `model/base_url` > persona 绑定 > **池内随机**（真实跑局入口）> mock（API 未指定时的默认）。显式指定 `model: "mock"` 的座位不受绑定与随机影响。
- `scripts/e2e_real.py` 与 TUI `--real` 自动开局同样按 persona 绑定构建座位（按 personas.json 顺序循环取用）；**未绑定的座位从 provider 模型池按对局 seed 随机分配**（同 seed 复现），CLI `--model` 可把池收窄为单个模型。
- **分配留痕**：每座位的最终模型随 `match_seat` 落库；完整分配记录（含 `basis: persona_binding|random` 与 `provider_id`）存于对局 `board.model_assignments`，`GET /api/matches/{id}` 可查，开局时同时打印「模型分配」清单。

## boards.json（板子预设）

```json
{
  "boards": [
    { "id": "p6-classic", "game_type": "werewolf", "ruleset": "minimal", "roles": { "wolf": 2, "seer": 1, "villager": 3 }, "wolf_meeting_rounds": 2, "max_days": 8 },
    { "id": "p8-classic", "game_type": "werewolf", "ruleset": "minimal", "roles": { "wolf": 2, "seer": 1, "villager": 5 }, "wolf_meeting_rounds": 2, "max_days": 8 },
    { "id": "p10-no-seer", "game_type": "werewolf", "ruleset": "minimal", "roles": { "wolf": 3, "villager": 7 }, "wolf_meeting_rounds": 2, "max_days": 8 },
    { "id": "p9-standard", "game_type": "werewolf", "ruleset": "standard-9", "roles": { "wolf": 3, "seer": 1, "witch": 1, "hunter": 1, "villager": 3 }, "wolf_meeting_rounds": 2, "max_days": 8 },
    { "id": "p12-standard", "game_type": "werewolf", "ruleset": "standard-12", "roles": { "wolf": 3, "wolf_king": 1, "seer": 1, "witch": 1, "hunter": 1, "guard": 1, "villager": 4 }, "wolf_meeting_rounds": 2, "max_days": 8 }
  ]
}
```

- 只配角色组合（D3）；服务端按 `ruleset` 分别 `validate_board`（见 [games/werewolf.md](games/werewolf.md)）。
- `ruleset`：`minimal`（v1）、`standard-9`（标准 9 人局，D15）、`standard-12`（标准 12 人局，D14）；`max_days` 天数上限，超时仍存活狼 → 狼胜。
- `custom` 板子由请求体给 roles，同样走校验。

## 密钥安全（全局安全规范）

- key 经 `api_key_env`（环境变量名）或 `api_key_file`（文件路径）解析；不进 JSON、不落库、不进日志。
- catalog API 脱敏；提交前全库 grep 无 key 明文。
- `backend/data/` 整目录不入 git（含 SQLite 库文件与配置）。

## .env 加载（D17）

启动时（API、`scripts/e2e_real.py`、TUI `--real`）自动读取 **`backend/app/config/.env`**（gitignore 内），把 `KEY=VALUE` 注入进程环境变量（已有环境变量优先，不被覆盖）；支持 `#` 注释与双引号包裹。providers.json 中的 `api_key_env` 填这里定义的变量名，例如：

```dotenv
BASE_URL=https://token-plan-cn.xiaomimimo.com/v1
API_KEY=tp-xxxxxxxx
MODEL=mimo-v2.6-flash
```

则 `providers.json` 里写 `"api_key_env": "API_KEY"` 即可。key 只在运行时由 `resolve_api_key` 解析进内存 seat_meta，落库仍是变量名。
