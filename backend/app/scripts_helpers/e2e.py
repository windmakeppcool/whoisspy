"""e2e 真实跑局的共享辅助：provider 选择与座位构建（供 scripts/e2e_real.py 与 TUI 复用）。"""

from __future__ import annotations

from typing import Any


def pick_provider(providers: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    """选第一个非 mock 的 provider 及其首个模型；只有 mock 时回落 mock。"""
    for p in providers:
        if p.get("id") != "mock" and p.get("models"):
            return p, p["models"][0]["id"]
    return providers[0], providers[0]["models"][0]["id"]


def build_real_seats(provider: dict[str, Any], model: str, *, n_players: int,
                     env: dict[str, str]) -> list[dict[str, Any]]:
    """构造 n 座位同 provider 的座位列表；key 变量未设置时直接报错（不静默走兜底）。"""
    api_key_env = provider.get("api_key_env", "")
    if api_key_env and not env.get(api_key_env):
        raise ValueError(
            f"环境变量 {api_key_env} 未设置（providers.json 引用了它），无法接入真实 LLM")
    from app.config.defaults import DEFAULT_PERSONAS

    return [{"seat": i, "persona_id": DEFAULT_PERSONAS[(i - 1) % len(DEFAULT_PERSONAS)]["id"],
             "name": "", "base_url": provider.get("base_url", ""),
             "api_key_env": api_key_env, "model": model}
            for i in range(1, n_players + 1)]
