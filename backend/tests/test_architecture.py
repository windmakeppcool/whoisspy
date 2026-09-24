"""架构约束测试（Red 先行，S5 回归）：engine 与具体游戏解耦。

契约见 docs/game-plugin.md：engine/agents/storage 不为具体游戏改动；
游戏规则只能出现在 games/<name>/ 里，engine 通过 StepContext 提供 IO 原语。
"""

from pathlib import Path

import app
from app.games.registry import create_game

ENGINE_DIR = Path(app.__file__).resolve().parent / "engine"
GAMES_DIR = Path(app.__file__).resolve().parent / "games"

# engine 里不允许出现的具体游戏痕迹（app.games.base 是契约模块，允许）
FORBIDDEN_IN_ENGINE = (
    "app.games.werewolf",
    "werewolf",
    "wolf_king",
    '"wolf"',
    "'wolf'",
    '"seer"',
    "'seer'",
    '"witch"',
    "'witch'",
    '"hunter"',
    "'hunter'",
    '"guard"',
    "'guard'",
    '"villager"',
    "'villager'",
    "sheriff",
    "vote.resolved",
    "night.kill_target",
    "day.speech_order",
)


def _engine_modules() -> list[Path]:
    return sorted(ENGINE_DIR.glob("*.py"))


class TestEngineIsGameAgnostic:
    def test_engine不出现任何具体游戏痕迹(self):
        assert _engine_modules(), "找不到 engine 模块"
        for path in _engine_modules():
            src = path.read_text(encoding="utf-8")
            for token in FORBIDDEN_IN_ENGINE:
                assert token not in src, f"{path.name} 出现了具体游戏痕迹: {token!r}"

    def test_runner只暴露一个步骤执行入口(self):
        src = (ENGINE_DIR / "runner.py").read_text(encoding="utf-8")
        for kind in ("night_start", "wolf_meeting", "sheriff_elect", "day_vote"):
            assert kind not in src, f"runner 不应认识游戏步骤 {kind!r}"
        assert "self._game.play(" in src, "runner 必须把步内流程委托给插件"

    def test_插件不反向依赖引擎内部(self):
        for path in sorted(GAMES_DIR.rglob("*.py")):
            src = path.read_text(encoding="utf-8")
            assert "app.engine.runner" not in src, f"{path.name} 反向依赖了 runner"
            assert "app.engine.context" not in src, f"{path.name} 反向依赖了 context 实现"


class TestPluginContract:
    def test_插件实现全部契约方法(self):
        game = create_game("werewolf")
        for name in ("validate_board", "deal", "initial_state", "next_step", "apply",
                     "action_schema", "validate_action", "neutral_action", "check_winner",
                     "visibility", "rule_slices", "slices_for", "play",
                     "memory_line", "phase_day"):
            assert callable(getattr(game, name, None)), f"插件缺少契约方法 {name}"

    def test_假游戏也能被引擎驱动(self):
        """engine 不认识游戏：一个最小假插件同样能跑（契约可替换性）。"""
        from tests.test_engine import FAKE_SPEC, FakeGame

        game = FakeGame()
        assert game.validate_board({}) == FAKE_SPEC
        assert game.next_step(game.initial_state(FAKE_SPEC, game.deal(FAKE_SPEC, __import__("random").Random(1)))).kind
