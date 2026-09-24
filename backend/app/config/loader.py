"""配置加载器：backend/data/*.json（providers/personas/boards）+ .env 注入。

契约见 docs/configuration.md（D13）：JSON + pydantic 校验，坏配置拒绝启动；
文件缺失回落内置默认（defaults.py / games.registry.PRESETS）。
API key 只经环境变量注入——配置里永远只有环境变量名，没有 key 本体。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from app.config.defaults import DEFAULT_PERSONAS, DEFAULT_PROVIDERS
from app.games.registry import PRESETS as DEFAULT_PRESETS

# 默认数据目录：backend/data（相对本文件：app/config → 上两级）
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
# 默认 .env：backend/app/config/.env
DEFAULT_ENV_FILE = Path(__file__).resolve().parent / ".env"


class ProviderModel(BaseModel):
    id: str
    base_url: str = ""
    api_key_env: str = ""
    currency: str = "CNY"
    models: list[dict[str, Any]] = []

    @field_validator("id")
    @classmethod
    def _id_nonempty(cls, v: str) -> str:
        if not v or not isinstance(v, str):
            raise ValueError("provider id 不能为空")
        return v


class ProvidersFile(BaseModel):
    providers: list[ProviderModel]


class PersonaModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    name: str
    style: str = ""
    strategy: str = ""


class PersonasFile(BaseModel):
    personas: list[PersonaModel]


class BoardModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    game_type: str = "werewolf"
    ruleset: str = "minimal"
    roles: dict[str, int]
    wolf_meeting_rounds: int = 2
    max_days: int = 8


class BoardsFile(BaseModel):
    boards: list[BoardModel]


@dataclass
class ConfigBundle:
    """一次加载的完整配置集合。"""

    providers: list[dict[str, Any]] = field(default_factory=list)
    personas: list[dict[str, Any]] = field(default_factory=list)
    boards: dict[str, dict[str, Any]] = field(default_factory=dict)


def _load_json(path: Path, model_cls: type[BaseModel], data_dir: Path) -> dict[str, Any]:
    """读取并校验单个 JSON 文件；解析/校验失败抛 ValueError（含文件名，拒绝启动）。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{path.name} 不是合法 JSON: {e}") from e
    try:
        return model_cls.model_validate(raw).model_dump(exclude_none=True)
    except Exception as e:
        raise ValueError(f"{path.name} 配置校验失败: {e}") from e


def load_config(data_dir: Path | str | None = None) -> ConfigBundle:
    """加载配置：有文件用文件，缺文件回落内置默认；坏文件直接抛 ValueError。"""
    d = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    bundle = ConfigBundle(
        providers=[dict(p) for p in DEFAULT_PROVIDERS],
        personas=[dict(p) for p in DEFAULT_PERSONAS],
        boards={k: dict(v) for k, v in DEFAULT_PRESETS.items()},
    )
    fp = d / "providers.json"
    if fp.exists():
        bundle.providers = list(_load_json(fp, ProvidersFile, d)["providers"])
    fg = d / "personas.json"
    if fg.exists():
        bundle.personas = list(_load_json(fg, PersonasFile, d)["personas"])
    fb = d / "boards.json"
    if fb.exists():
        parsed = _load_json(fb, BoardsFile, d)
        bundle.boards = {b["id"]: b for b in parsed["boards"]}
    return bundle


def apply_boards(bundle: ConfigBundle) -> None:
    """把 bundle.boards 覆盖写入 games.registry.PRESETS（JSON 板子即权威）。"""
    import app.games.registry as reg

    reg.PRESETS.clear()
    reg.PRESETS.update(bundle.boards)


def apply_default_boards() -> None:
    """恢复内置板子预设（测试用）。"""
    import app.games.registry as reg

    reg.PRESETS.clear()
    reg.PRESETS.update(DEFAULT_PRESETS)


def parse_env_file(path: Path) -> dict[str, str]:
    """解析 .env 文件为 dict：KEY=VALUE，支持 # 注释与双引号包裹；坏行忽略。"""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def load_env_file(path: Path | None = None, *, override: bool = False) -> None:
    """把 .env 中的变量注入 os.environ（默认不覆盖已存在的环境变量）。"""
    for key, value in parse_env_file(path if path is not None else DEFAULT_ENV_FILE).items():
        if override or key not in os.environ:
            os.environ[key] = value


def resolve_api_key(api_key_env: str) -> str:
    """按环境变量名取真实 key；未设置返回空串（调用方决定如何报错/兜底）。"""
    if not api_key_env:
        return ""
    return os.environ.get(api_key_env, "")
