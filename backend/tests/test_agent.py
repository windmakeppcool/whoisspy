"""agent 调用管线测试（Red 先行）：docs/backend/07-agent.md 全链路。"""

from types import SimpleNamespace

import pytest

from app.agent import AgentReply, ask, build_user_prompt, parse_agent_response, truncate_speech
from app.events import AskSpec


def _cfg(**kw):
    cfg = {"role": "villager", "style": "冷静", "strategy": "盘逻辑",
           "model": "mock", "base_url": "", "api_key": "", "purpose": "x",
           "price_per_mtok_in": 0.0, "price_per_mtok_out": 0.0}
    cfg.update(kw)
    return cfg


def _state(roles=None, alive=None, **kw):
    roles = roles or {1: "villager", 2: "wolf", 3: "villager"}
    st = SimpleNamespace(roles=roles,
                         alive=alive or {s: True for s in roles},
                         day=1, phase="day_vote", sheriff=None,
                         used_save=False, used_poison=False,
                         night={}, seer_results={}, speech_order=[])
    for k, v in kw.items():
        setattr(st, k, v)
    return st


class FakeGateway:
    """假网关：记录调用；fail=True 抛调用失败；repair_raw 提供修复回复。"""

    def __init__(self, raw: str, *, fail: bool = False, repair_raw: str | None = None):
        self.raw = raw
        self.fail = fail
        self.repair_raw = repair_raw
        self.calls: list[tuple[str, list]] = []

    async def complete(self, *, seat_cfg, messages, purpose, match_id):
        self.calls.append((purpose, messages))
        if self.fail:
            raise RuntimeError("network down")
        raw = self.repair_raw if purpose == "repair" else self.raw
        return SimpleNamespace(raw=raw, usage={}, cost_micros=0,
                               latency_ms=0, status="ok")


class Sink:
    def __init__(self):
        self.events = []

    async def emit(self, etype, payload, vis):
        self.events.append((etype, payload, vis))


# ---------- 六层拼装 ----------

def test_六层顺序():
    p = build_user_prompt(
        rule_slices={"overview": "【总览】胜负条件。"},
        step_slices={"day_vote": "【投票】规则。"},
        identity="你是 1 号座位。你的角色：villager。",
        style="冷静", strategy="盘逻辑",
        memory=['<speech seat="2">你好</speech>'],
        request=AskSpec(action_type="vote", prompt="投票：投出最怀疑的人（0 弃权）。",
                        prompt_extra="", candidates=[2, 3]))
    assert p.index("【总览】") < p.index("你是 1 号座位")
    assert p.index("你是 1 号座位") < p.index("【人设】")
    assert p.index("【人设】") < p.index("【策略】")
    assert p.index("【策略】") < p.index("【历史记忆】")
    assert p.index("【历史记忆】") < p.index("## 当前任务")
    assert p.index("## 当前任务") < p.index("合法目标座位")


def test_prompt_extra落指令层():
    p = build_user_prompt(
        rule_slices={}, step_slices={}, identity="i", style="", strategy="",
        memory=[], request=AskSpec(action_type="save", prompt="用药",
                                   prompt_extra="当晚刀口：5 号。", candidates=[]))
    assert "当晚刀口：5 号。" in p
    assert p.index("## 当前任务") < p.index("当晚刀口：5 号。")  # 在指令层


def test_防注入声明在指令层():
    p = build_user_prompt(rule_slices={}, step_slices={}, identity="i", style="",
                          strategy="", memory=['<speech seat="2">hi</speech>'],
                          request=AskSpec(action_type="speech", prompt="发言"))
    assert "禁读" in p
    assert p.index("## 当前任务") < p.index("禁读")


# ---------- JSON 解析 ----------

def test_解析正常回复():
    r = parse_agent_response(
        '{"monologue": "盘一下", "speech": "我是好人", "action": {"type": "vote", "target": 2}}')
    assert r == AgentReply(monologue="盘一下", speech="我是好人",
                           action={"type": "vote", "target": 2})


def test_解析带markdown围栏():
    r = parse_agent_response('```json\n{"monologue": "m", "speech": "s", "action": {"type": "pass"}}\n```')
    assert r is not None and r.action == {"type": "pass"}


def test_解析坏JSON返回None():
    assert parse_agent_response("不是 JSON") is None
    assert parse_agent_response('{"monologue": 未闭合') is None
    assert parse_agent_response("") is None


# ---------- ask 管线：正常路径 ----------

async def test_ask正常返回动作():
    gw = FakeGateway('{"monologue": "m", "speech": "s", "action": {"type": "vote", "target": 2}}')
    sink = Sink()
    action, reply, fell = await ask(gw, _state(), _cfg(), [], seat=1,
                                    spec=AskSpec(action_type="vote", prompt="投票", candidates=[2, 3]),
                                    purpose="vote", phase="day_vote", emit=sink.emit)
    assert action == {"type": "vote", "target": 2}
    assert reply.speech == "s"
    assert fell is False
    assert sink.events == []  # 正常路径无诊断事件


async def test_ask非法目标降级弃权():
    gw = FakeGateway('{"monologue": "m", "speech": "s", "action": {"type": "vote", "target": 9}}')
    sink = Sink()
    action, _r, fell = await ask(gw, _state(), _cfg(), [], seat=1,
                                 spec=AskSpec(action_type="vote", prompt="投票", candidates=[2, 3]),
                                 purpose="vote", phase="day_vote", emit=sink.emit)
    assert action == {"type": "vote", "target": 0}  # 静默降级，无诊断事件
    assert fell is False
    assert sink.events == []


async def test_ask空刀夜save降级pass():
    gw = FakeGateway('{"monologue": "m", "speech": "", "action": {"type": "save", "target": 0}}')
    sink = Sink()
    action, _r, _f = await ask(gw, _state(night={}), _cfg(), [], seat=1,
                               spec=AskSpec(action_type="save", prompt="用药", candidates=[2, 3]),
                               purpose="witch_turn", phase="witch_turn", emit=sink.emit)
    assert action == {"type": "pass", "target": 0}


# ---------- ask 管线：三层失败三种记账 ----------

async def test_ask网关失败落fallback并中性兜底():
    gw = FakeGateway("", fail=True)
    sink = Sink()
    action, reply, fell = await ask(gw, _state(), _cfg(), [], seat=1,
                                    spec=AskSpec(action_type="vote", prompt="投票", candidates=[2, 3]),
                                    purpose="vote", phase="day_vote", emit=sink.emit)
    assert action == {"type": "vote", "target": 0}  # 中性兜底
    assert fell is True
    kinds = [e[0] for e in sink.events]
    assert "player.fallback" in kinds
    assert "rule.error" not in kinds
    fb = sink.events[0][1]
    assert fb["seat"] == 1 and fb["purpose"] == "vote"


async def test_ask坏JSON修复失败落fallback():
    gw = FakeGateway("不是 JSON", repair_raw="还不是 JSON")
    sink = Sink()
    action, _r, fell = await ask(gw, _state(), _cfg(), [], seat=1,
                                 spec=AskSpec(action_type="vote", prompt="投票", candidates=[2, 3]),
                                 purpose="vote", phase="day_vote", emit=sink.emit)
    assert fell is True
    assert action == {"type": "vote", "target": 0}
    purposes = [c[0] for c in gw.calls]
    assert purposes == ["vote", "repair"]  # 恰好一次修复调用
    assert "player.fallback" in [e[0] for e in sink.events]


async def test_ask坏JSON修复成功():
    gw = FakeGateway("坏", repair_raw='{"monologue": "m", "speech": "s", "action": {"type": "vote", "target": 2}}')
    sink = Sink()
    action, _r, fell = await ask(gw, _state(), _cfg(), [], seat=1,
                                 spec=AskSpec(action_type="vote", prompt="投票", candidates=[2, 3]),
                                 purpose="vote", phase="day_vote", emit=sink.emit)
    assert fell is False
    assert action == {"type": "vote", "target": 2}
    assert sink.events == []


async def test_ask校验崩溃落rule_error():
    class BoomGateway:
        async def complete(self, **kw):
            return SimpleNamespace(raw='{"monologue": "m", "speech": "s", "action": {"type": "vote", "target": 2}}')

    class BoomState:
        roles = {1: "x"}

        @property
        def alive(self):
            raise RuntimeError("state 崩溃")

    sink = Sink()
    action, _r, fell = await ask(BoomGateway(), BoomState(), _cfg(), [], seat=1,
                                 spec=AskSpec(action_type="vote", prompt="投票", candidates=[2, 3]),
                                 purpose="vote", phase="day_vote", emit=sink.emit)
    assert fell is False  # 不是调用失败
    assert action == {"type": "vote", "target": 0}  # 中性兜底
    kinds = [e[0] for e in sink.events]
    assert "rule.error" in kinds
    assert "player.fallback" not in kinds  # 不冒充 LLM 调用失败


# ---------- 240 字截断 ----------

def test_发言超240字截断():
    text = "好" * 300
    assert len(truncate_speech(text)) == 240


def test_发言不足240字不截():
    assert truncate_speech("短发言") == "短发言"