# 09 配置与密钥（config.py）

配置文件格式与现行 `backend/data/` 完全兼容（providers.json / personas.json / .env 原样可用）；
boards.json 退出（板子是代码常量，[05-rules.md](05-rules.md)）。

## 一、providers.json（接入预设库）

```json
{ "providers": [
  { "id": "demo", "base_url": "https://api.example.com/v1", "api_key_env": "DEMO_API_KEY",
    "currency": "CNY",
    "models": [ { "id": "model-a", "price_per_mtok_in": 2.0, "price_per_mtok_out": 8.0 } ] } ] }
```

- 模型单价三个字段（每 1M token）：`price_per_mtok_in / price_per_mtok_out /
  price_per_mtok_cached_in`（缺省=输入价）；
- `model` 引用、`provider_id` 交叉校验：模型必须属于声明的 provider，否则启动即报错。

## 二、personas.json（style + strategy，D11/D18）

```json
{ "personas": [
  { "id": "aggressive-liar", "name": "悍跳强攻型",
    "style": "语气强硬、短句、爱用反问……", "strategy": "拿狼必悍跳预言家……",
    "provider_id": "demo", "model": "model-a" } ] }
```

`provider_id/model` 为可选绑定（选手卡=性格+模型）：座位未显式指定接入时自动展开，
同桌混搭不同模型。

## 三、.env 加载

启动时读 `backend/app/.env`（gitignore 内）：`KEY=VALUE` 注入环境变量，已有环境变量优先；
支持 `#` 注释与双引号。providers.json 的 `api_key_env` 填这里定义的变量名。

## 四、座位接入构建（跑局前）

CLI 构建座位快照（固化进 `match_seat`，历史对局不依赖后续配置变更——D10/D19）：

- 座位按 personas.json 顺序循环取 persona（9 座 → 前 9 个 persona）；
- 模型来源优先级（沿用 D19）：**persona 绑定 > 分配池内按对局 seed 随机**；
  分配池 = CLI `--model` 收窄为单模型，否则 provider 全部模型；mock 模式全部 `model="mock"`；
- 随机分配用 `Random(seed)`（同 seed 复现），分配结果（`basis: persona_binding|random`
  + `provider_id`）写入 `match.created.model_assignments` 并打印清单；
- 真实模式预检：涉及的所有 `api_key_env` 必须能解析到非空值，缺一个直接失败退出
  （绝不静默跑出一局全兜底的假局）；
- 显式给出的 `base_url` 必须命中 providers.json 某条（白名单沿用——headless 下它防的是
  配置文件被塞进任意外部地址把 key 发出去）。

## 五、安全不变量

1. key 只经 `api_key_env` 环境变量名出现：不进 JSON、不落库、不进日志、不进 trace；
2. `backend/data/`、`exports/`、trace 目录整体不入 git；
3. 配置用 pydantic 校验，坏配置启动即失败（不静默降级）。
