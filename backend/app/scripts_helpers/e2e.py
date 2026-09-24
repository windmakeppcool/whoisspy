"""e2e 真实跑局的共享辅助：provider 选择与座位构建（供 scripts/e2e_real.py 与 TUI 复用）。"""

from __future__ import annotations

from typing import Any


def pick_provider(providers: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    """选第一个非 mock 的 provider 及其首个模型；只有 mock 时回落 mock。"""
    for p in providers:
        if p.get("id") != "mock" and p.get("models"):
            return p, p["models"][0]["id"]
    return providers[0], providers[0]["models"][0]["id"]


def assignment_pool_for(provider: dict[str, Any], model_id: str = "") -> list[str]:
    """随机分配池：CLI --model 指定时收窄为该模型，否则 provider 全部模型。"""
    if model_id:
        return [model_id]
    return [m["id"] for m in provider.get("models", [])] or ["mock"]


def build_real_seats(provider: dict[str, Any], model: str, *, n_players: int,
                     env: dict[str, str],
                     personas: list[dict[str, Any]] | None = None,
                     providers: list[dict[str, Any]] | None = None,
                     seed: int = 0,
                     assignment_pool: list[str] | None = None,
                     ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """构造 n 座位座位列表，返回 (座位列表, 分配记录)；key 变量未设置时直接报错。

    座位模型来源优先级（D18/D19）：
      1. persona 绑定（provider_id + model）→ basis="persona_binding"
      2. 从 assignment_pool（默认 provider 的模型列表）随机分配 → basis="random"
         （Random(seed) 可复现，同一对局 seed 重跑分配一致）
    providers 是 persona 绑定可引用的完整 provider 表；缺省时绑定 fallback 到默认 provider。
    """
    from random import Random

    from app.config.defaults import DEFAULT_PERSONAS

    rng = Random(seed)
    pool = list(assignment_pool) if assignment_pool else [m["id"] for m in provider.get("models", [])] or [model]
    persona_list = personas if personas is not None else DEFAULT_PERSONAS
    providers_all = {p["id"]: p for p in (providers or [provider])}

    # 涉及的所有 provider 的 key 变量都必须已设置
    key_vars: set[str] = set()
    if provider.get("api_key_env"):
        key_vars.add(provider["api_key_env"])
    for persona in persona_list:
        pid = persona.get("provider_id")
        if pid and pid in providers_all and providers_all[pid].get("api_key_env"):
            key_vars.add(providers_all[pid]["api_key_env"])
        elif pid and pid not in providers_all:
            raise ValueError(f"persona {persona.get('id')!r} 绑定的 provider {pid!r} 不存在")
    missing = [k for k in sorted(key_vars) if not env.get(k)]
    if missing:
        raise ValueError(
            f"环境变量 {', '.join(missing)} 未设置（providers.json 引用了它），无法接入真实 LLM")

    seats: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []
    for i in range(1, n_players + 1):
        persona = persona_list[(i - 1) % len(persona_list)]
        base_url, api_key_env = provider.get("base_url", ""), provider.get("api_key_env", "")
        pid = persona.get("provider_id")
        if pid and persona.get("model"):
            p = providers_all.get(pid, provider)
            base_url, api_key_env = p.get("base_url", ""), p.get("api_key_env", "")
            seat_model, basis = persona["model"], "persona_binding"
        else:
            seat_model, basis = rng.choice(pool), "random"
        seats.append({"seat": i, "persona_id": persona["id"], "name": "",
                      "base_url": base_url, "api_key_env": api_key_env,
                      "model": seat_model})
        assignments.append({"seat": i, "persona_id": persona["id"],
                            "model": seat_model, "basis": basis,
                            "provider_id": pid or provider.get("id", "")})
    return seats, assignments
