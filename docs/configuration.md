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
