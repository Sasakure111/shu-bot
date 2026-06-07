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
    mp_cost: int
    power: float
    description: str
    status: str
    status_chance: int


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
