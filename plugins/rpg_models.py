"""Shared data shapes for the fantasy roguelike RPG."""

from __future__ import annotations

from typing import Literal, TypedDict


StatKey = Literal["hp", "atk", "def", "mat", "mdf", "mp", "spd"]
RandomStatKey = Literal["crit", "resist", "luck", "charm"]
DamageType = Literal["physical", "magical", "support", "special"]
RunMode = Literal["standard", "creative"]
EnemyRank = Literal["very_weak", "weak", "normal", "strong", "very_strong"]
NodeType = Literal["battle", "elite", "npc", "shop", "mystery", "rest", "boss"]


CoreStats = TypedDict(
    "CoreStats",
    {
        "hp": int,
        "atk": int,
        "def": int,
        "mat": int,
        "mdf": int,
        "mp": int,
        "spd": int,
    },
)


class RandomStats(TypedDict):
    crit: int
    resist: int
    luck: int
    charm: int


class SkillTemplate(TypedDict, total=False):
    id: str
    name: str
    type: DamageType
    quality: str  # 品质（决定技能书掉落/价格/强度档；不参与结算，纯标签）
    class_req: str | None  # 职业限定 id；None=通用技
    innate: bool  # True=出生技，不作为技能书掉落/出售
    mp_cost: int
    power: float  # 伤害技：伤害倍率（作用于 ATK/MAT）；支援治疗技：治疗倍率（作用于 MAT）
    hits: int  # 多段攻击次数，默认 1
    description: str
    status: str
    status_chance: int
    status_pool: list[str]  # 随机异常池：命中时从中挑一个附加（与 status 二选一）
    # 限时增益（固定数值，与道具 buff 同口径，作用于核心/骰子属性）。
    # support 技与伤害技均可带；伤害技的 self_buff/enemy_debuff 在伤害结算后施加。
    self_buff: dict[str, object]  # {"name": str, "mods": {stat: int}, "duration": int} 施于自身
    enemy_debuff: dict[str, object]  # {"name": str, "mods": {stat: -int}, "duration": int} 施于敌人
    # 治疗 / 回蓝（百分比按各自最大值；heal_hp_flat 为定额、不吃 MAT）
    heal_hp_percent: int
    heal_hp_flat: int
    heal_mp_self: int  # 回自身 MP，按最大 MP 的百分比
    # 传奇特殊机制钩子
    special: str  # low_hp_bonus / execute / crit_override / pierce_def / smite_status
    special_args: dict[str, object]


class ClassTemplate(TypedDict, total=False):
    id: str
    name: str
    description: str
    base: CoreStats
    growth: CoreStats
    base_resist: int  # 基础抗性%（总抗性% = 骰子抗性 d20 × 3 + 基础抗性%）
    base_crit: int  # 基础暴击%（总暴击% = 骰子暴击 d20 × 3 + 基础暴击%）
    starting_skills: list[str]
    heal_multiplier: float  # 牧师特殊：治疗加成（回复量 × 此值）
    charm_bonus: int  # 吟游诗人特殊：魅力固定加成，可突破上限


class UnitStatProfile(TypedDict):
    """敌方/Boss 单档位的显式基础属性，来自数值设定文档。"""

    base: CoreStats
    growth: CoreStats
    base_resist: int
    base_crit: int


class ItemTemplate(TypedDict, total=False):
    id: str
    name: str
    type: str
    quality: str
    price: int
    description: str
    effects: dict[str, object]
    shop: bool  # False 表示不进商店池（仅掉落/事件获得）


class EnemyRankProfile(TypedDict, total=False):
    name: str
    skill_chance: int
    reward_multiplier: float
    exp_reward: int
    gold_reward: int
    drop_chance: int
    drop_quality_weights: dict[str, int]


class EnemyTemplate(TypedDict, total=False):
    id: str
    name: str
    chapter: int
    preferred_damage: Literal["physical", "magical", "mixed"]
    skills: list[str]


class BossTemplate(TypedDict, total=False):
    id: str
    name: str
    chapter: int
    level: int
    skills: list[str]
    mechanic: str
    reward: dict[str, object]


class ChapterDefinition(TypedDict):
    id: int
    name: str
    min_floors: int
    max_floors: int
    node_weights: dict[NodeType, int]
    boss_id: str
