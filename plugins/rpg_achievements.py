"""成就系统：定义 + 判定。

判定全部在一局结束时（通关 / 转生 / 死亡都经过 _finish_run）一次性比对，
依据一个上下文字典（见 build_context 的字段说明），不直接触碰数据库。
解锁的落库与提示由 rogue_rpg.py 负责。
"""

from __future__ import annotations

from typing import Any, Callable

# 三个章节 Boss 纪念物（集齐 = #22）
BOSS_KEEPSAKES = ("dawn_treant_token", "storm_witch_token", "rift_dragon_token")


def _social_total(ctx: dict[str, Any]) -> int:
    ach = ctx["ach"]
    return ach["persuade"]["n"] + ach["deceive"]["n"] + ach["intimidate"]["n"]


def _social_ok(ctx: dict[str, Any]) -> int:
    ach = ctx["ach"]
    return ach["persuade"]["ok"] + ach["deceive"]["ok"] + ach["intimidate"]["ok"]


# 每条成就：id、名称、描述、是否隐藏、判定函数(ctx -> bool)。
# 顺序即展示顺序（与成就表 #1~#22 一致）。
ACHIEVEMENTS: list[dict[str, Any]] = [
    {"id": "1", "name": "新手上路", "desc": "通关 1 次标准模式冒险", "hidden": False,
     "check": lambda c: c["won"] and c["wins"] >= 1},
    {"id": "2", "name": "老练的冒险者", "desc": "通关 10 次标准模式冒险", "hidden": False,
     "check": lambda c: c["won"] and c["wins"] >= 10},
    {"id": "3", "name": "大冒险家", "desc": "通关 25 次标准模式冒险", "hidden": False,
     "check": lambda c: c["won"] and c["wins"] >= 25},
    {"id": "4", "name": "酒馆至尊黄金冒险者！", "desc": "通关 50 次标准模式冒险", "hidden": False,
     "check": lambda c: c["won"] and c["wins"] >= 50},
    {"id": "5", "name": "真正的天选之子", "desc": "开局幸运值 ≤ 0，并通关一次标准模式冒险", "hidden": True,
     "check": lambda c: c["won"] and c["start_luck"] <= 0},
    {"id": "6", "name": "这才是高情商", "desc": "局内社交行为 ≥ 3 次，且全部失败", "hidden": False,
     "check": lambda c: _social_total(c) >= 3 and _social_ok(c) == 0},
    {"id": "7", "name": "万人迷？", "desc": "通关时魅力值 ≥ 20", "hidden": False,
     "check": lambda c: c["won"] and c["charm"] >= 20},
    {"id": "8", "name": "照了个镜子就转生了", "desc": "局内转生时魅力值 ≥ 20", "hidden": False,
     "check": lambda c: c["result"] == "rebirth" and c["charm"] >= 20},
    {"id": "9", "name": "嘉豪", "desc": "局内社交行为 ≥ 5 次，且全部失败", "hidden": False,
     "check": lambda c: _social_total(c) >= 5 and _social_ok(c) == 0},
    {"id": "10", "name": "现充", "desc": "局内社交行为 ≥ 3 次，且全部成功", "hidden": False,
     "check": lambda c: _social_total(c) >= 3 and _social_ok(c) == _social_total(c)},
    {"id": "11", "name": "精神小伙……？！", "desc": "局内威吓 ≥ 3 次，且全部失败", "hidden": False,
     "check": lambda c: c["ach"]["intimidate"]["n"] >= 3 and c["ach"]["intimidate"]["ok"] == 0},
    {"id": "12", "name": "毕竟老夫我也不是什么魔鬼嘛", "desc": "局内威吓 ≥ 3 次，且全部成功", "hidden": False,
     "check": lambda c: c["ach"]["intimidate"]["n"] >= 3
     and c["ach"]["intimidate"]["ok"] == c["ach"]["intimidate"]["n"]},
    {"id": "13", "name": "你还是别干这行了", "desc": "局内欺骗 ≥ 3 次，且全部失败", "hidden": False,
     "check": lambda c: c["ach"]["deceive"]["n"] >= 3 and c["ach"]["deceive"]["ok"] == 0},
    {"id": "14", "name": "欺诈师", "desc": "局内欺骗 ≥ 3 次，且全部成功", "hidden": False,
     "check": lambda c: c["ach"]["deceive"]["n"] >= 3
     and c["ach"]["deceive"]["ok"] == c["ach"]["deceive"]["n"]},
    {"id": "15", "name": "以理服人？", "desc": "局内说服 ≥ 3 次，且全部失败", "hidden": False,
     "check": lambda c: c["ach"]["persuade"]["n"] >= 3 and c["ach"]["persuade"]["ok"] == 0},
    {"id": "16", "name": "以理服人！", "desc": "局内说服 ≥ 3 次，且全部成功", "hidden": False,
     "check": lambda c: c["ach"]["persuade"]["n"] >= 3
     and c["ach"]["persuade"]["ok"] == c["ach"]["persuade"]["n"]},
    {"id": "17", "name": "社恐", "desc": "一局内完全没有社交行为，并成功通关", "hidden": False,
     "check": lambda c: c["won"] and _social_total(c) == 0},
    {"id": "18", "name": "战斗爽！", "desc": "一局内战斗（含 Boss 战）≥ 10 次，并成功通关", "hidden": False,
     "check": lambda c: c["won"] and c["ach"]["battles"] >= 10},
    {"id": "19", "name": "天选之子", "desc": "局内获得【天选之子】状态，并成功通关", "hidden": False,
     "check": lambda c: c["won"] and "天选之子" in c["run_statuses"]},
    {"id": "20", "name": "？", "desc": "局内获得【霉运】状态", "hidden": False,
     "check": lambda c: "霉运" in c["run_statuses"]},
    {"id": "21", "name": "幸运极了！", "desc": "游戏结束时幸运值 = -20", "hidden": False,
     "check": lambda c: c["luck"] == -20},
    {"id": "22", "name": "BOSS杀手", "desc": "集齐 3 个章节的 Boss 纪念物", "hidden": False,
     "check": lambda c: set(BOSS_KEEPSAKES).issubset(c["owned_keepsakes"])},
]

ACHIEVEMENTS_BY_ID: dict[str, dict[str, Any]] = {a["id"]: a for a in ACHIEVEMENTS}


def new_run_counters() -> dict[str, Any]:
    """一局开始时的成就计数器初值（存入 state['flags']['ach']）。"""
    return {
        "persuade": {"n": 0, "ok": 0},
        "deceive": {"n": 0, "ok": 0},
        "intimidate": {"n": 0, "ok": 0},
        "battles": 0,
    }


def evaluate(ctx: dict[str, Any]) -> list[str]:
    """返回本局满足条件的成就 id 列表（不含去重/已解锁过滤，调用方处理）。"""
    hits: list[str] = []
    for ach in ACHIEVEMENTS:
        check: Callable[[dict[str, Any]], bool] = ach["check"]
        try:
            if check(ctx):
                hits.append(ach["id"])
        except Exception:
            # 单条判定异常不应阻断其余成就
            continue
    return hits
