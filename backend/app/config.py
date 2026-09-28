"""配置加载与座位接入构建（docs/backend/09-config.md）。

providers.json / personas.json 格式与旧系统兼容（backend/data/ 原样可用）；
key 只经 api_key_env 环境变量解析进内存，绝不落库。
"""

from __future__ import annotations

import os
from random import Random
from typing import Any

from pydantic import BaseModel, ValidationError


class ProviderModel(BaseModel):
    id: str
    price_per_mtok_in: float = 0.0
    price_per_mtok_out: float = 0.0
    price_per_mtok_cached_in: float | None = None


class Provider(BaseModel):
    id: str
    base_url: str = ""
    api_key_env: str = ""
    currency: str = ""
    models: list[ProviderModel] = []


class Persona(BaseModel):
    id: str
    name: str = ""
    style: str = ""
    strategy: str = ""
    provider_id: str | None = None
    model: str | None = None


class ProvidersFile(BaseModel):
    providers: list[Provider]


class PersonasFile(BaseModel):
    personas: list[Persona]


def _providers_from_dict(data: dict[str, Any]) -> list[Provider]:
    return ProvidersFile.model_validate(data).providers


def _personas_from_dict(data: dict[str, Any]) -> list[Persona]:
    return PersonasFile.model_validate(data).personas


def load_providers(path: str) -> ProvidersFile:
    """加载 providers.json（坏配置拒绝加载）。"""
    import json

    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    try:
        return ProvidersFile.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"providers.json 非法：{e}") from e


def load_personas(path: str) -> PersonasFile:
    """加载 personas.json（坏配置拒绝加载）。"""
    import json

    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    try:
        return PersonasFile.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"personas.json 非法：{e}") from e


def load_env_file(path: str, env: dict[str, str] | None = None) -> dict[str, str]:
    """读取 .env 注入环境变量（已有环境变量优先；支持 # 注释与双引号包裹）。"""
    env = env if env is not None else os.environ
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip()
                if len(value) >= 2 and value[0] == value[-1] == '"':
                    value = value[1:-1]
                if key and key not in env:
                    env[key] = value
    except FileNotFoundError:
        pass  # .env 可缺省
    return env


def _pick_provider(providers: list[Provider]) -> Provider:
    """默认池源：首个非 mock provider；只有 mock 时回落 mock。"""
    for p in providers:
        if p.id != "mock" and p.models:
            return p
    return providers[0] if providers else Provider(id="mock", models=[ProviderModel(id="mock")])


def build_seats(*, n_players: int, personas: list[Persona],
                providers: list[Provider], env: dict[str, str],
                model: str | None = None, seed: int = 0
                ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """构造 n 个座位，返回 (座位列表, 分配记录)。

    模型来源优先级（D19）：persona 绑定 > 分配池内按 seed 随机（池 = --model 收窄
    或默认 provider 全部模型）。涉及的所有 api_key_env 必须已设置，缺一个直接报错
    （绝不静默跑出一局全兜底的假局）。
    """
    rng = Random(seed)
    provider_map = {p.id: p for p in providers}
    pool_provider = _pick_provider(providers)

    # 交叉校验：persona 绑定的 provider/model 必须存在
    for persona in personas:
        if persona.provider_id and persona.provider_id not in provider_map:
            raise ValueError(
                f"persona {persona.id!r} 绑定的 provider {persona.provider_id!r} 不存在")
        if persona.provider_id and persona.model:
            p = provider_map[persona.provider_id]
            if persona.model not in {m.id for m in p.models}:
                raise ValueError(
                    f"persona {persona.id!r} 绑定模型 {persona.model!r} 不属于 "
                    f"provider {persona.provider_id!r}")

    pool = [model] if model else [m.id for m in pool_provider.models] or ["mock"]
    seats: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []
    for i in range(1, n_players + 1):
        persona = personas[(i - 1) % len(personas)]
        if persona.provider_id and persona.model:
            p = provider_map[persona.provider_id]
            seat_model, basis = persona.model, "persona_binding"
        else:
            p = pool_provider
            seat_model, basis = rng.choice(pool), "random"
        if p.api_key_env and not env.get(p.api_key_env):
            raise ValueError(
                f"环境变量 {p.api_key_env} 未设置（providers.json 引用了它），无法接入真实 LLM")
        m = next((m for m in p.models if m.id == seat_model), ProviderModel(id=seat_model))
        seats.append({
            "seat": i, "persona_id": persona.id, "style": persona.style,
            "strategy": persona.strategy, "provider_id": p.id,
            "base_url": p.base_url, "api_key_env": p.api_key_env,
            "model": seat_model,
            "price_per_mtok_in": m.price_per_mtok_in,
            "price_per_mtok_out": m.price_per_mtok_out,
            "price_per_mtok_cached_in": m.price_per_mtok_cached_in,
        })
        assignments.append({"seat": i, "persona_id": persona.id,
                            "model": seat_model, "basis": basis,
                            "provider_id": p.id})
    return seats, assignments