"""Pure rule engine for the fantasy roguelike RPG."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from typing import Any

from . import rpg_data


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def clamp_int(value: float, minimum: int, maximum: int) -> int:
    return int(clamp(round(value), minimum, maximum))


def make_rng(seed: str | int | None = None) -> random.Random:
    return random.Random(seed)


def weighted_choice(weights: dict[str, int], rng: random.Random) -> str:
    total = sum(max(0, weight) for weight in weights.values())
    if total <= 0:
        raise ValueError("weights must contain at least one positive value")

    roll = rng.randint(1, total)
    cursor = 0
    for key, weight in weights.items():
        cursor += max(0, weight)
        if roll <= cursor:
            return key
    return next(reversed(weights))


def get_class_template(class_id: str) -> dict[str, Any]:
    for template in rpg_data.STANDARD_CLASSES:
        if template["id"] == class_id:
            return dict(template)
    raise ValueError(f"unknown class id: {class_id}")


def get_skill_template(skill_id: str) -> dict[str, Any]:
    for skill in rpg_data.BASE_SKILLS:
        if skill["id"] == skill_id:
            return dict(skill)
    raise ValueError(f"unknown skill id: {skill_id}")


def get_item_template(item_id: str) -> dict[str, Any]:
    for item in rpg_data.ITEM_POOLS:
        if item["id"] == item_id:
            return dict(item)
    for book in rpg_data.SKILL_BOOKS:  # 技能书单独注册，不混进随机道具池
        if book["id"] == item_id:
            return dict(book)
    raise ValueError(f"unknown item id: {item_id}")


def learn_skill(character: dict[str, Any], skill_id: str) -> tuple[bool, str]:
    """尝试学会技能。返回 (是否学会, 原因码)：
    already_known（已会）/ slots_full（技能栏满，需先 /遗忘）/ learned（学会）。
    """
    skills = character.setdefault("skills", [])
    if skill_id in skills:
        return False, "already_known"
    if len(skills) >= rpg_data.MAX_SKILL_SLOTS:
        return False, "slots_full"
    skills.append(skill_id)
    return True, "learned"


def forget_skill(character: dict[str, Any], index: int) -> tuple[bool, str, str | None]:
    """遗忘技能栏第 index 个技能（0 基）。返回 (是否成功, 原因码, 技能名)。
    至少保留 1 个技能；出生技（innate）不可遗忘。
    """
    skills = character.get("skills", [])
    if index < 0 or index >= len(skills):
        return False, "no_skill", None
    if len(skills) <= 1:
        return False, "last_skill", None
    skill_id = skills[index]
    try:
        tpl = get_skill_template(skill_id)
    except ValueError:
        tpl = {}
    if tpl.get("innate"):
        return False, "innate", str(tpl.get("name", skill_id))
    skills.pop(index)
    return True, "forgotten", str(tpl.get("name", skill_id))


def roll_skill_book(
    class_id: str | None,
    rng: random.Random,
    *,
    qualities: Sequence[str] | None = None,
) -> dict[str, Any] | None:
    """随机抽一本技能书：只给"通用书 + 当前职业专属书"，可按品质过滤。返回书道具模板或 None。"""
    candidates = [
        dict(book) for book in rpg_data.SKILL_BOOKS
        if book.get("class_req") in (None, class_id)
        and (qualities is None or book.get("quality") in set(qualities))
    ]
    if not candidates:
        return None
    return rng.choice(candidates)


def get_boss_template(boss_id: str) -> dict[str, Any]:
    for boss in rpg_data.BOSS_DEFINITIONS:
        if boss["id"] == boss_id:
            return dict(boss)
    raise ValueError(f"unknown boss id: {boss_id}")


def exp_to_next_level(level: int) -> int | None:
    level = int(level)
    if level >= rpg_data.MAX_PLAYER_LEVEL:
        return None
    return rpg_data.LEVEL_EXP_BASE + rpg_data.LEVEL_EXP_PER_LEVEL * level


def add_character_exp(character: dict[str, Any], amount: int) -> tuple[dict[str, Any], int]:
    updated = dict(character)
    level = int(updated.get("level", 1))
    exp = int(updated.get("exp", 0)) + int(amount)
    leveled = 0

    while level < rpg_data.MAX_PLAYER_LEVEL:
        required = exp_to_next_level(level)
        if required is None or exp < required:
            break
        exp -= required
        level += 1
        leveled += 1

    if level >= rpg_data.MAX_PLAYER_LEVEL:
        level = rpg_data.MAX_PLAYER_LEVEL
        exp = 0

    updated["level"] = level
    updated["exp"] = exp
    if leveled:
        # 升级后按职业成长重算面板；新增的 HP/MP 上限同步补进当前值，避免“上限涨了但血没涨”。
        old_hp_max = int(updated.get("stats", {}).get("hp", 0))
        old_mp_max = int(updated.get("stats", {}).get("mp", 0))
        recompute_character_stats(updated)
        new_hp_max = int(updated["stats"]["hp"])
        new_mp_max = int(updated["stats"]["mp"])
        updated["current_hp"] = min(new_hp_max, int(updated.get("current_hp", new_hp_max)) + max(0, new_hp_max - old_hp_max))
        updated["current_mp"] = min(new_mp_max, int(updated.get("current_mp", new_mp_max)) + max(0, new_mp_max - old_mp_max))
    return updated, leveled


def roll_random_stats(rng: random.Random) -> dict[str, int]:
    return {
        "crit": rng.randint(rpg_data.RANDOM_STAT_MIN, rpg_data.RANDOM_STAT_MAX),
        "resist": rng.randint(rpg_data.RANDOM_STAT_MIN, rpg_data.RANDOM_STAT_MAX),
        "luck": rng.randint(rpg_data.RANDOM_STAT_MIN, rpg_data.RANDOM_STAT_MAX),
        "charm": rng.randint(rpg_data.RANDOM_STAT_MIN, rpg_data.RANDOM_STAT_MAX),
    }


def calculate_profile_stats(
    base: dict[str, Any],
    growth: dict[str, Any],
    level: int,
) -> dict[str, int]:
    """按《数值设定》通用公式 stat = base + growth ×(Lv-1) 计算七项核心属性。"""
    level = clamp_int(level, 1, rpg_data.MAX_PLAYER_LEVEL)
    steps = level - 1
    stats: dict[str, int] = {}
    for key in CORE_STAT_KEYS:
        stats[key] = int(base[key]) + int(growth.get(key, 0)) * steps
    stats["mp"] = min(rpg_data.MAX_MP, stats["mp"])
    stats["spd"] = min(rpg_data.MAX_SPD, stats["spd"])
    return stats


def calculate_class_stats(class_id: str, level: int) -> dict[str, int]:
    template = get_class_template(class_id)
    return calculate_profile_stats(template["base"], template["growth"], level)


def make_inventory(item_ids: Sequence[str]) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for item_id in item_ids:
        add_item_to_inventory({"inventory": inventory}, item_id)
    return inventory


CORE_STAT_KEYS = ("hp", "atk", "def", "mat", "mdf", "mp", "spd")
RANDOM_STAT_KEYS = ("crit", "resist", "luck", "charm")

# 骰子属性上下限：暴击/抗性不可为负，幸运/魅力可为负；上限统一 20。
# 标注“可突破上限”的加成走 character["overcap_random"]，在 clamp 之后额外叠加。
RANDOM_STAT_BOUNDS: dict[str, tuple[int | None, int]] = {
    "crit": (0, 20),
    "resist": (0, 20),
    "luck": (None, 20),
    "charm": (None, 20),
}


def clamp_random_stat(key: str, value: int) -> int:
    low, high = RANDOM_STAT_BOUNDS[key]
    if low is not None:
        value = max(low, value)
    return min(high, value)


def item_category(item: dict[str, Any]) -> str:
    """把道具归到 equipment / attribute / consumable 三类之一。"""
    item_type = item.get("type", "")
    if item_type in rpg_data.EQUIPMENT_TYPES:
        return "equipment"
    if item_type in rpg_data.ATTRIBUTE_TYPES:
        return "attribute"
    return "consumable"


def special_effect_id(item: dict[str, Any]) -> str | None:
    effects = item.get("effects", {})
    if not isinstance(effects, dict):
        return None
    value = effects.get("special")
    return str(value) if value else None


def is_special_item(item: dict[str, Any]) -> bool:
    return item.get("type") == "special" or special_effect_id(item) is not None


def is_active_special_item(item: dict[str, Any]) -> bool:
    effects = item.get("effects", {})
    return is_special_item(item) and isinstance(effects, dict) and effects.get("trigger") == "active"


def inventory_backpack_slots(character: dict[str, Any]) -> int:
    bonus = int(character.get("backpack_slot_bonus", 0))
    return clamp_int(rpg_data.MAX_BACKPACK_SLOTS + bonus, rpg_data.MAX_BACKPACK_SLOTS, rpg_data.MAX_BACKPACK_SLOTS_WITH_BONUS)


def item_category_by_id(item_id: str) -> str:
    return item_category(get_item_template(item_id))


def list_consumables(character: dict[str, Any]) -> list[dict[str, Any]]:
    """按背包顺序返回可在战斗中使用的消耗品格（渲染与处理共用，保证编号一致）。"""
    result: list[dict[str, Any]] = []
    for entry in character.get("inventory", []):
        try:
            item = get_item_template(entry["id"])
        except ValueError:
            continue
        if item.get("type") == "skillbook":  # 技能书走局外学习，不在战斗道具菜单
            continue
        if item_category(item) == "consumable" and (not is_special_item(item) or is_active_special_item(item)):
            result.append(entry)
    return result


def aggregate_item_bonuses(character: dict[str, Any]) -> tuple[dict[str, int], dict[str, int]]:
    """汇总穿戴装备 + 背包内属性道具带来的核心属性 / 随机属性加成。"""
    stat_bonus: dict[str, int] = {}
    random_bonus: dict[str, int] = {}

    def _apply(item: dict[str, Any]) -> None:
        for key, value in item.get("effects", {}).items():
            if not isinstance(value, (int, float)):
                continue
            if key in CORE_STAT_KEYS:
                stat_bonus[key] = stat_bonus.get(key, 0) + int(value)
            elif key in RANDOM_STAT_KEYS:
                random_bonus[key] = random_bonus.get(key, 0) + int(value)

    for entry in character.get("equipment", []):
        try:
            _apply(get_item_template(entry["id"]))
        except ValueError:
            continue

    for entry in character.get("inventory", []):
        try:
            item = get_item_template(entry["id"])
        except ValueError:
            continue
        if item_category(item) != "attribute":
            continue
        for _ in range(int(entry.get("quantity", 1))):  # 属性道具持有即生效、可叠效果
            _apply(item)

    return stat_bonus, random_bonus


def _ensure_perm_core_bonus(character: dict[str, Any]) -> dict[str, Any]:
    """确保 character['perm_core_bonus'] 存在（事件给的永久核心属性加成，与等级成长分开存）。

    老存档没有这个字段：它们的 base_stats 当年是“职业 1 级属性 + 永久加成”
    （升级从不成长），据此反推出永久加成，迁移时才不会丢掉已获得的永久属性。
    """
    perm = character.get("perm_core_bonus")
    if perm is not None:
        return perm
    class_id = character.get("class_id")
    old_base = character.get("base_stats")
    if class_id and old_base is not None:
        class_l1 = calculate_class_stats(str(class_id), 1)
        perm = {key: int(old_base.get(key, 0)) - int(class_l1.get(key, 0)) for key in CORE_STAT_KEYS}
    else:
        perm = {}
    character["perm_core_bonus"] = perm
    return perm


def recompute_character_stats(character: dict[str, Any]) -> dict[str, Any]:
    """重算面板：base = 职业按当前等级成长 + 永久事件加成，再叠加装备与属性道具。"""
    perm = _ensure_perm_core_bonus(character)
    class_id = character.get("class_id")
    if class_id:  # 玩家：每次按 stat = base + growth×(Lv-1) 重建，等级变化即生效
        level = int(character.get("level", 1))
        class_base = calculate_class_stats(str(class_id), level)
        base = {key: int(class_base.get(key, 0)) + int(perm.get(key, 0)) for key in CORE_STAT_KEYS}
        character["base_stats"] = base
    else:  # 兼容无职业的异常数据
        base = character.get("base_stats")
        if base is None:
            base = dict(character.get("stats", {}))
            character["base_stats"] = base
    base_random = character.get("base_random_stats")
    if base_random is None:
        base_random = dict(character.get("random_stats", {}))
        character["base_random_stats"] = base_random
    character.setdefault("equipment", [])

    stat_bonus, random_bonus = aggregate_item_bonuses(character)

    stats = {key: int(base.get(key, 0)) + int(stat_bonus.get(key, 0)) for key in CORE_STAT_KEYS}
    stats["hp"] = max(1, stats["hp"])
    stats["mp"] = clamp_int(stats["mp"], 0, rpg_data.MAX_MP)
    stats["spd"] = clamp_int(stats["spd"], 0, rpg_data.MAX_SPD)
    overcap = character.get("overcap_random", {})  # “可突破上限”的加成（如吟游诗人魅力 +5）
    random_stats = {
        key: clamp_random_stat(key, int(base_random.get(key, 0)) + int(random_bonus.get(key, 0)))
        + int(overcap.get(key, 0))
        for key in RANDOM_STAT_KEYS
    }

    character["stats"] = stats
    character["random_stats"] = random_stats
    character["current_hp"] = min(int(character.get("current_hp", stats["hp"])), stats["hp"])
    character["current_mp"] = min(int(character.get("current_mp", stats["mp"])), stats["mp"])
    return character


def can_add_item(character: dict[str, Any], item_id: str) -> tuple[bool, str]:
    """判断能否把道具放进背包，返回 (是否可行, 原因码)。"""
    item = get_item_template(item_id)
    category = item_category(item)
    inventory = character.get("inventory", [])
    equipment = character.get("equipment", [])
    capacity = inventory_backpack_slots(character)

    if is_special_item(item):
        if any(e["id"] == item_id for e in inventory) or any(e["id"] == item_id for e in equipment):
            return False, "duplicate_special"
        if special_effect_id(item) == "backpack_slot" and len(inventory) == capacity and capacity < rpg_data.MAX_BACKPACK_SLOTS_WITH_BONUS:
            return True, "new"
        if len(inventory) >= capacity:
            return False, "backpack_full"
        return True, "new"

    if category == "equipment":
        if any(e["id"] == item_id for e in inventory) or any(e["id"] == item_id for e in equipment):
            return False, "duplicate_equipment"  # 同名装备只能持 1 个
        if len(inventory) >= capacity:
            return False, "backpack_full"
        return True, "new"

    if category == "attribute":  # 不可叠到同格，但可占多个格子
        if len(inventory) >= capacity:
            return False, "backpack_full"
        return True, "new"

    # consumable：先找未满的同名格叠加，满了或没有再开新格
    for entry in inventory:
        if entry["id"] == item_id and int(entry.get("quantity", 1)) < rpg_data.MAX_STACK:
            return True, "stack"
    if len(inventory) >= capacity:
        return False, "backpack_full"
    return True, "new"


def add_item_to_inventory(character: dict[str, Any], item_id: str) -> tuple[bool, str]:
    """按三类规则把道具加入背包；属性道具入包后会重算面板。"""
    ok, reason = can_add_item(character, item_id)
    if not ok:
        return False, reason
    inventory = character.setdefault("inventory", [])
    if reason == "stack":
        for entry in inventory:
            if entry["id"] == item_id and int(entry.get("quantity", 1)) < rpg_data.MAX_STACK:
                entry["quantity"] = int(entry.get("quantity", 1)) + 1
                break
    else:
        inventory.append({"id": item_id, "quantity": 1})
    if item_category_by_id(item_id) == "attribute" and character.get("base_stats") is not None:
        recompute_character_stats(character)
    return True, reason


def equip_item(character: dict[str, Any], inventory_index: int) -> tuple[bool, str, dict[str, Any] | None]:
    """把背包第 inventory_index 个道具穿到装备栏，成功后重算面板。"""
    inventory = character.setdefault("inventory", [])
    equipment = character.setdefault("equipment", [])
    if inventory_index < 0 or inventory_index >= len(inventory):
        return False, "no_item", None
    item = get_item_template(inventory[inventory_index]["id"])
    if item_category(item) != "equipment":
        return False, "not_equipment", item
    if len(equipment) >= rpg_data.MAX_EQUIPPED:
        return False, "slots_full", item
    inventory.pop(inventory_index)  # 装备格内 quantity 恒为 1
    equipment.append({"id": item["id"]})
    recompute_character_stats(character)
    return True, "ok", item


def unequip_item(character: dict[str, Any], equip_index: int) -> tuple[bool, str, dict[str, Any] | None]:
    """卸下装备栏第 equip_index 件装备放回背包，成功后重算面板。"""
    equipment = character.setdefault("equipment", [])
    inventory = character.setdefault("inventory", [])
    if equip_index < 0 or equip_index >= len(equipment):
        return False, "no_item", None
    item = get_item_template(equipment[equip_index]["id"])
    if len(inventory) >= inventory_backpack_slots(character):
        return False, "backpack_full", item
    equipment.pop(equip_index)
    inventory.append({"id": item["id"], "quantity": 1})
    recompute_character_stats(character)
    return True, "ok", item


def create_standard_character(
    class_id: str,
    rng: random.Random,
    *,
    name: str | None = None,
    background: str = "",
) -> dict[str, Any]:
    template = get_class_template(class_id)
    level = 1
    stats = calculate_class_stats(class_id, level)
    random_stats = roll_random_stats(rng)
    # 吟游诗人特殊：魅力 +5，可突破上限 —— 放进 overcap，在 clamp 之后叠加
    charm_bonus = int(template.get("charm_bonus", 0))
    overcap_random = {"charm": charm_bonus} if charm_bonus else {}
    character = {
        "name": name or template["name"],
        "class_id": class_id,
        "class_name": template["name"],
        "description": template["description"],
        "level": level,
        "exp": 0,
        "next_exp": exp_to_next_level(level),
        "base_stats": dict(stats),
        "base_random_stats": dict(random_stats),
        "perm_core_bonus": {},  # 事件给的永久核心属性加成，与等级成长分开累计
        "stats": dict(stats),
        "current_hp": stats["hp"],
        "current_mp": stats["mp"],
        "random_stats": dict(random_stats),
        "overcap_random": overcap_random,
        "base_resist": int(template.get("base_resist", 0)),
        "base_crit": int(template.get("base_crit", 0)),
        "heal_multiplier": float(template.get("heal_multiplier", 1.0)),
        "skills": list(template["starting_skills"]),
        "gold": rpg_data.STARTING_GOLD,
        "inventory": make_inventory(rpg_data.STARTING_INVENTORY),
        "equipment": [],
        "statuses": [],
        "background": background,
    }
    return recompute_character_stats(character)


def enemy_variant_for_damage(rng: random.Random) -> str:
    """小怪变体随机：A（物理倾向）/ B（法系倾向）各 1/2 概率。"""
    return rng.choice(["A", "B"])


def enemy_level_for_node(player_level: int, chapter: int, node_type: str) -> int:
    if node_type == "boss":
        boss = next(
            (boss for boss in rpg_data.BOSS_DEFINITIONS if int(boss["chapter"]) == int(chapter)),
            None,
        )
        if boss is not None:
            return int(boss["level"])
    # 每章敌人等级限定在固定区间内：第1章 1-3、第2章 4-6、第3章 7-9
    # （= [3*章-2, 3*章]，正好比本章 Boss 低 1~3 级）。
    # 敌人仍随玩家等级浮动，但即便玩家越级（例如读入高等级存档）也按本章上下限封顶，
    # 不会刷出超出本章范围的怪。精英取区间高位。
    chapter_max = min(3 * int(chapter), rpg_data.MAX_PLAYER_LEVEL)
    chapter_min = max(1, chapter_max - 2)
    bonus = 1 if node_type == "elite" else 0
    return clamp_int(int(player_level) + bonus, chapter_min, chapter_max)


def roll_enemy_rank(rng: random.Random, *, elite: bool = False) -> str:
    if elite:
        return weighted_choice({"strong": 70, "very_strong": 30}, rng)
    return weighted_choice(rpg_data.ENEMY_RANK_WEIGHTS, rng)


def choose_enemy_template(chapter: int, rng: random.Random) -> dict[str, Any]:
    candidates = [
        template
        for template in rpg_data.ENEMY_TEMPLATES
        if int(template["chapter"]) <= int(chapter)
    ]
    if not candidates:
        candidates = list(rpg_data.ENEMY_TEMPLATES)
    return dict(rng.choice(candidates))


def generate_enemy(
    chapter: int,
    level: int,
    rng: random.Random,
    *,
    rank: str | None = None,
    template_id: str | None = None,
    elite: bool = False,
) -> dict[str, Any]:
    rank_id = rank or roll_enemy_rank(rng, elite=elite)
    rank_profile = dict(rpg_data.ENEMY_RANKS[rank_id])
    template = (
        next((dict(item) for item in rpg_data.ENEMY_TEMPLATES if item["id"] == template_id), None)
        if template_id
        else choose_enemy_template(chapter, rng)
    )
    if template is None:
        raise ValueError(f"unknown enemy template id: {template_id}")

    variant = enemy_variant_for_damage(rng)
    profile = rpg_data.ENEMY_RANK_STATS[rank_id][variant]
    stats = calculate_profile_stats(profile["base"], profile["growth"], level)
    skills: list[str] = []
    if template.get("skills") and rng.randint(1, 100) <= int(rank_profile["skill_chance"]):
        skill_count = 2 if rank_id == "very_strong" and len(template["skills"]) >= 2 else 1
        skills = rng.sample(template["skills"], k=skill_count)

    random_stats = roll_random_stats(rng)  # 骰子属性同样 d20（暴击/抗性/幸运/魅力）
    random_stats["charm"] = 0
    return {
        "id": template["id"],
        "name": template["name"],
        "chapter": int(chapter),
        "level": int(level),
        "rank": rank_id,
        "rank_name": rank_profile["name"],
        "preferred_damage": template.get("preferred_damage", "physical"),
        "stats": stats,
        "current_hp": stats["hp"],
        "current_mp": stats["mp"],
        "random_stats": random_stats,
        "base_resist": int(profile["base_resist"]),
        "base_crit": int(profile["base_crit"]),
        "skills": skills,
        "statuses": [],
    }


def generate_boss(boss_id: str, rng: random.Random) -> dict[str, Any]:
    boss = get_boss_template(boss_id)
    profile = rpg_data.BOSS_STATS
    stats = calculate_profile_stats(profile["base"], profile["growth"], int(boss["level"]))
    random_stats = roll_random_stats(rng)
    random_stats["charm"] = 0
    return {
        "id": boss["id"],
        "name": boss["name"],
        "chapter": int(boss["chapter"]),
        "level": int(boss["level"]),
        "rank": "boss",
        "rank_name": "Boss",
        "mechanic": boss["mechanic"],
        "stats": stats,
        "current_hp": stats["hp"],
        "current_mp": stats["mp"],
        "random_stats": random_stats,
        "base_resist": int(profile["base_resist"]),
        "base_crit": int(profile["base_crit"]),
        "skills": list(boss["skills"]),
        "statuses": [],
        "reward": dict(boss["reward"]),
    }


def total_resist(actor: dict[str, Any]) -> float:
    """总抗性% = 骰子抗性(d20) × 3 + 基础抗性%（来自《数值设定》）。"""
    dice_resist = int(actor.get("random_stats", {}).get("resist", 0))
    base_resist = int(actor.get("base_resist", 0))
    return clamp(dice_resist * 3 + base_resist, 0, 100)


def choose_enemy_action(enemy: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """敌方 AI：决定本回合普攻还是放技能。

    规则：无技能或 MP 不足 → 普攻；血量低于 40% 且有支援技 → 较大概率自愈；
    否则有技能的敌人约 60% 概率放伤害技（可附带异常），其余回合普攻。
    """
    skills = list(enemy.get("skills", []))
    if not skills:
        return {"type": "attack"}
    current_mp = int(enemy.get("current_mp", enemy.get("stats", {}).get("mp", 0)))
    affordable = [sid for sid in skills if current_mp >= int(get_skill_template(sid).get("mp_cost", 0))]
    if not affordable:
        return {"type": "attack"}

    max_hp = max(1, int(enemy.get("stats", {}).get("hp", 1)))
    hp_ratio = int(enemy.get("current_hp", max_hp)) / max_hp
    support = [sid for sid in affordable if get_skill_template(sid).get("type") == "support"]
    if support and hp_ratio < 0.4 and rng.random() < 0.6:
        return {"type": "skill", "skill_id": rng.choice(support)}

    damage_skills = [
        sid for sid in affordable if get_skill_template(sid).get("type") in ("physical", "magical")
    ]
    pool = damage_skills or affordable
    if pool and rng.random() < 0.6:
        return {"type": "skill", "skill_id": rng.choice(pool)}
    return {"type": "attack"}


def effective_crit_rate(actor: dict[str, Any], bonus_crit: int = 0) -> float:
    """实战暴击率% = (基础暴击 + 骰子暴击 + 其他暴击增益) × 幸运/10 + 0.1。"""
    random_stats = actor.get("random_stats", {})
    base_crit = int(actor.get("base_crit", 0))
    dice_crit = int(random_stats.get("crit", 0))
    luck = int(random_stats.get("luck", 0))
    return clamp((base_crit + dice_crit + int(bonus_crit)) * (luck / 10) + 0.1, 0.1, 100)


def dodge_rate(actor: dict[str, Any]) -> float:
    luck = int(actor.get("random_stats", {}).get("luck", 0))
    return clamp(luck, 0, 100)


def status_apply_rate(target: dict[str, Any]) -> float:
    """状态命中率 = max(0%, 100 - 总抗性%)。"""
    return clamp(100 - total_resist(target), 0, 100)


def status_damage(caster: dict[str, Any], target: dict[str, Any], base_value: float) -> int:
    """状态伤害 = floor(MAT*10/(100+MDF) × 基础值 × max(0,100-总抗性%)/100)，不吃暴击。"""
    mat = max(0, float(caster.get("stats", {}).get("mat", 0)))
    mdf = max(0, float(target.get("stats", {}).get("mdf", 0)))
    resist_factor = max(0.0, 100 - total_resist(target)) / 100
    raw = (mat * 10) / (100 + mdf) * float(base_value) * resist_factor
    return max(0, math.floor(raw))


def status_modifiers(actor: dict[str, Any]) -> tuple[float, int]:
    """汇总 actor 当前负面状态对属性的即时修正：返回 (ATK/MAT 乘子, SPD 增量)。

    诅咒使 ATK/MAT ×0.75；麻痹每层使 SPD −攻速惩罚。增益(buff)类不在此处（已烤进面板）。
    """
    atk_mat_mult = 1.0
    spd_delta = 0
    for status in actor.get("statuses", []):
        defn = rpg_data.STATUS_DEFINITIONS.get(status.get("id"), {})
        if "atk_mat_mult" in defn:
            atk_mat_mult *= float(defn["atk_mat_mult"])
        if "spd_penalty_per_stack" in defn:
            spd_delta -= int(defn["spd_penalty_per_stack"]) * int(status.get("stacks", 1))
    return atk_mat_mult, spd_delta


def effective_spd(actor: dict[str, Any]) -> int:
    """考虑麻痹减速后的实际 SPD（用于出手顺序、连击、打断）。"""
    _atk_mult, spd_delta = status_modifiers(actor)
    return int(clamp(int(actor.get("stats", {}).get("spd", 0)) + spd_delta, 0, rpg_data.MAX_SPD))


def tick_statuses(
    actor: dict[str, Any],
    opponent: dict[str, Any],
    rng: random.Random,
) -> tuple[dict[str, Any], list[str], bool]:
    """回合开始结算 actor 身上的状态：伤害类扣血、麻痹类标记跳过，并递减持续回合。

    返回 (更新后的 actor, 叙述行, 是否跳过本回合行动)。opponent 作为伤害类状态的施法方取 MAT。
    """
    statuses = [dict(s) for s in actor.get("statuses", [])]
    if not statuses:
        return actor, [], False
    actor = dict(actor)
    stats = dict(actor.get("stats", {}))  # 副本，buff 到期时在此撤销加成
    random_stats = dict(actor.get("random_stats", {}))
    logs: list[str] = []
    skip = False
    remaining: list[dict[str, Any]] = []
    hp = int(actor.get("current_hp", stats.get("hp", 0)))
    for st in statuses:
        if st.get("kind") == "buff":  # 限时增益：到期撤销其属性加成
            st["duration"] = int(st["duration"]) - 1
            if st["duration"] > 0:
                remaining.append(st)
            else:
                for mod_key, mod_value in st.get("mods", {}).items():
                    if mod_key in CORE_STAT_KEYS:
                        stats[mod_key] = int(stats.get(mod_key, 0)) - int(mod_value)
                    elif mod_key in RANDOM_STAT_KEYS:
                        random_stats[mod_key] = int(random_stats.get(mod_key, 0)) - int(mod_value)
                logs.append(f"【{st.get('name', '增益')}】效果结束。")
            continue

        defn = rpg_data.STATUS_DEFINITIONS.get(st["id"], {})
        name = str(defn.get("name", st["id"]))
        stacks = int(st.get("stacks", 1))
        tag = f"{name}×{stacks}" if stacks > 1 else name
        base_value = float(defn.get("base_value", 0))
        if base_value > 0:  # 持续伤害（按层数放大）
            dmg = status_damage(opponent, actor, base_value * stacks)
            hp = max(0, hp - dmg)
            logs.append(f"【{tag}】持续伤害 {dmg}。")
        if defn.get("skip_action"):
            skip = True
            logs.append(f"【{name}】发作，本回合无法行动。")
        st["duration"] = int(st["duration"]) - 1
        if st["duration"] > 0:
            remaining.append(st)
        else:
            logs.append(f"【{name}】效果结束。")
    actor["stats"] = stats
    actor["random_stats"] = random_stats
    actor["current_hp"] = min(hp, int(stats.get("hp", hp)))
    actor["statuses"] = remaining
    return actor, logs, skip


def apply_buff(
    actor: dict[str, Any],
    *,
    name: str,
    mods: dict[str, int],
    duration: int,
    status_id: str = "buff",
) -> dict[str, Any]:
    """给 actor 施加一个限时增益：立即叠加核心属性加成，并记录到 statuses 供到期撤销。

    注意：mods 只作用于核心属性（atk/def/mat/mdf/spd 等）；HP/MP 回复请走消耗品回复效果。
    """
    actor = dict(actor)
    stats = dict(actor.get("stats", {}))
    random_stats = dict(actor.get("random_stats", {}))
    for mod_key, mod_value in mods.items():
        if mod_key in CORE_STAT_KEYS:
            stats[mod_key] = int(stats.get(mod_key, 0)) + int(mod_value)
        elif mod_key in RANDOM_STAT_KEYS:  # 限时增益对骰子属性直接生效，不受 0-20 上限约束
            random_stats[mod_key] = int(random_stats.get(mod_key, 0)) + int(mod_value)
    actor["stats"] = stats
    actor["random_stats"] = random_stats
    statuses = [dict(s) for s in actor.get("statuses", [])]
    statuses.append(
        {"id": status_id, "name": name, "kind": "buff", "duration": int(duration), "mods": dict(mods)}
    )
    actor["statuses"] = statuses
    return actor


def _add_status(statuses: list[dict[str, Any]], status_id: str) -> None:
    """施加状态：已存在则刷新持续回合，可叠加的再加一层（封顶 max_stacks）。"""
    defn = rpg_data.STATUS_DEFINITIONS.get(status_id, {})
    duration = int(defn.get("duration", 1))
    max_stacks = int(defn.get("max_stacks", 1))
    for existing in statuses:
        if existing.get("id") == status_id:
            existing["duration"] = duration
            if max_stacks > 1:
                existing["stacks"] = min(max_stacks, int(existing.get("stacks", 1)) + 1)
            return
    statuses.append({"id": status_id, "duration": duration, "stacks": 1})


def apply_consumable_effects(
    character: dict[str, Any],
    item: dict[str, Any],
    rng: random.Random,
) -> tuple[dict[str, Any], list[str]]:
    """结算一件消耗品的全部效果，返回 (更新后的角色, 叙述行)。支持：
    heal_hp / heal_mp（定额）、heal_hp_percent / heal_mp_percent（按上限百分比）、
    heal_full（回满）、cleanse（"all" 或数量 N，清除负面状态）、buff（限时增益）、
    self_status（自体负面，可带 chance%）。
    """
    character = dict(character)
    stats = dict(character.get("stats", {}))
    character["stats"] = stats
    effects = item.get("effects", {})
    lines: list[str] = []
    special = special_effect_id(item)

    max_hp = max(1, int(stats.get("hp", 1)))
    max_mp = max(0, int(stats.get("mp", 0)))
    cur_hp = int(character.get("current_hp", max_hp))
    cur_mp = int(character.get("current_mp", max_mp))

    if special == "abyss_contract":
        perm = _ensure_perm_core_bonus(character)
        for key in ("atk", "mat"):
            perm[key] = int(perm.get(key, 0)) + max(1, round(int(stats.get(key, 0)) * 0.30))
        perm["hp"] = int(perm.get("hp", 0)) - max(1, round(max_hp * 0.20))
        character = recompute_character_stats(character)
        character["current_hp"] = min(int(character["stats"]["hp"]), max(1, int(character.get("current_hp", max_hp))))
        lines.append("签下深渊契约：HP永久下降，ATK与MAT永久上升。")
        return character, lines

    if special == "reroll_random_keep_best":
        old_stats = dict(character.get("base_random_stats", character.get("random_stats", {})))
        rolled = roll_random_stats(rng)
        character["base_random_stats"] = {
            key: max(int(old_stats.get(key, 0)), int(rolled.get(key, 0)))
            for key in RANDOM_STAT_KEYS
        }
        character = recompute_character_stats(character)
        final = character["random_stats"]
        lines.append(
            "命运改写完成："
            f"暴击{final['crit']} 抗性{final['resist']} 幸运{final['luck']} 魅力{final['charm']}。"
        )
        return character, lines

    if special == "final_reward_multiplier":
        character["final_reward_multiplier"] = max(float(character.get("final_reward_multiplier", 1.0)), float(effects.get("mult", 2.0)))
        lines.append("创世纪录展开：本局正常结局最终奖励倍率变为2。")
        return character, lines

    if effects.get("heal_full"):
        cur_hp, cur_mp = max_hp, max_mp
        lines.append("HP 与 MP 完全恢复。")
    if "heal_hp" in effects:
        cur_hp = min(max_hp, cur_hp + int(effects["heal_hp"]))
        lines.append(f"回复 HP {int(effects['heal_hp'])}。")
    if "heal_mp" in effects:
        cur_mp = min(max_mp, cur_mp + int(effects["heal_mp"]))
        lines.append(f"回复 MP {int(effects['heal_mp'])}。")
    if "heal_hp_percent" in effects:
        amount = max_hp * int(effects["heal_hp_percent"]) // 100
        cur_hp = min(max_hp, cur_hp + amount)
        lines.append(f"回复 HP {amount}（{int(effects['heal_hp_percent'])}% 上限）。")
    if "heal_mp_percent" in effects:
        amount = max_mp * int(effects["heal_mp_percent"]) // 100
        cur_mp = min(max_mp, cur_mp + amount)
        lines.append(f"回复 MP {amount}（{int(effects['heal_mp_percent'])}% 上限）。")
    character["current_hp"] = cur_hp
    character["current_mp"] = cur_mp

    cleanse_ids = effects.get("cleanse_ids")  # 定向解除指定状态（如解毒剂只解中毒）
    if cleanse_ids:
        wanted = set(cleanse_ids)
        statuses = [dict(s) for s in character.get("statuses", [])]
        removed = [s for s in statuses if s.get("id") in wanted]
        if removed:
            character["statuses"] = [s for s in statuses if s.get("id") not in wanted]
            names = "、".join(
                str(rpg_data.STATUS_DEFINITIONS.get(s["id"], {}).get("name", s["id"])) for s in removed
            )
            lines.append(f"解除了：{names}。")
        else:
            lines.append("没有对应的负面状态可解除。")

    cleanse = effects.get("cleanse")
    if cleanse:
        statuses = [dict(s) for s in character.get("statuses", [])]
        negatives = [s for s in statuses if s.get("id") in rpg_data.NEGATIVE_STATUS_IDS]
        if not negatives:
            lines.append("没有可清除的负面状态。")
        elif cleanse == "all" or cleanse is True:
            character["statuses"] = [s for s in statuses if s.get("id") not in rpg_data.NEGATIVE_STATUS_IDS]
            lines.append("清除了所有负面状态。")
        else:
            remove = set(id(s) for s in rng.sample(negatives, k=min(int(cleanse), len(negatives))))
            character["statuses"] = [s for s in statuses if id(s) not in remove]
            lines.append(f"清除了 {len(remove)} 个负面状态。")

    buff = effects.get("buff")
    if buff:
        mods = dict(buff.get("mods", {}))
        character = apply_buff(
            character,
            name=str(buff.get("name", "增益")),
            mods=mods,
            duration=int(buff.get("duration", 1)),
        )
        mod_text = "、".join(f"{key}{value:+d}" for key, value in mods.items())
        lines.append(f"获得增益【{buff.get('name', '增益')}】：{mod_text}，持续 {int(buff.get('duration', 1))} 回合。")

    self_status = effects.get("self_status")
    if self_status and rng.randint(1, 100) <= int(self_status.get("chance", 100)):
        status_id = str(self_status["id"])
        defn = rpg_data.STATUS_DEFINITIONS.get(status_id, {})
        statuses = [dict(s) for s in character.get("statuses", [])]
        _add_status(statuses, status_id)
        character["statuses"] = statuses
        lines.append(f"副作用：你陷入了【{defn.get('name', status_id)}】。")

    return character, lines


def apply_skill_status(
    skill: dict[str, Any],
    target: dict[str, Any],
    rng: random.Random,
) -> tuple[dict[str, Any], str | None]:
    """技能命中后按 技能proc率 × 状态命中率 尝试给 target 附加状态，已有则刷新持续回合。"""
    status_id = skill.get("status")
    if not status_id:  # E4：随机异常池，命中时从中挑一个
        pool = skill.get("status_pool")
        if pool:
            status_id = rng.choice(list(pool))
    if not status_id:
        return target, None
    defn = rpg_data.STATUS_DEFINITIONS.get(status_id)
    if not defn:
        return target, None
    proc = int(skill.get("status_chance", 0)) * status_apply_rate(target) / 100
    if rng.random() * 100 >= proc:
        return target, None
    target = dict(target)
    statuses = [dict(s) for s in target.get("statuses", [])]
    _add_status(statuses, status_id)
    target["statuses"] = statuses
    return target, f"{target.get('name', '目标')} 陷入了【{defn['name']}】。"


def calculate_damage(
    attacker: dict[str, Any],
    defender: dict[str, Any],
    *,
    damage_type: str = "physical",
    attack_bonus: float = 0.0,
    power_multiplier: float = 1.0,
    crit_multiplier: float = 1.5,
    defense_mult: float = 1.0,
    rng: random.Random,
) -> dict[str, Any]:
    dodged = rng.random() * 100 < dodge_rate(defender)
    if dodged:
        return {"damage": 0, "dodged": True, "critical": False}

    critical = rng.random() * 100 < effective_crit_rate(attacker)
    multiplier = crit_multiplier if critical else 1.0
    stats = attacker["stats"]
    target_stats = defender["stats"]
    coefficient = round(rng.uniform(0.95, 1.05), 2)  # 系数 k，取两位小数
    atk_mat_mult, _spd = status_modifiers(attacker)  # 诅咒使 ATK/MAT ×0.75

    if damage_type == "magical":
        attack = max(0, float(stats.get("mat", 0))) * atk_mat_mult
        defense = max(0, float(target_stats.get("mdf", 0)))
    else:
        attack = max(0, float(stats.get("atk", 0))) * atk_mat_mult
        defense = max(0, float(target_stats.get("def", 0)))
    defense *= max(0.0, float(defense_mult))  # 无视防御类技能（pierce_def）按系数削减目标防御

    # power_multiplier 为技能伤害倍率（普攻=1.0），作用在攻击力上；attack_bonus 为额外平摊加成
    attack = attack * float(power_multiplier) + float(attack_bonus)
    # 攻击伤害 = (ATK * 100 * k) / (100 + DEF)，暴击 ×1.5，最终向下取整
    raw = (attack * 100 * coefficient) / (100 + defense) * multiplier
    # 易伤：冰冻受物理 +50%（受指定类型攻击时放大）
    for status in defender.get("statuses", []):
        defn = rpg_data.STATUS_DEFINITIONS.get(status.get("id"), {})
        if defn.get("vuln_type") == damage_type:
            raw *= 1 + float(defn.get("vuln_mult", 0))
    return {"damage": max(1, math.floor(raw)), "dodged": False, "critical": critical}


def _wake_on_hit(defender_after: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """受击时按概率提前解除“受击解除”类状态（昏睡 50%）。"""
    statuses = defender_after.get("statuses", [])
    kept = [
        st for st in statuses
        if not (
            rpg_data.STATUS_DEFINITIONS.get(st.get("id"), {}).get("wake_on_hit")
            and rng.randint(1, 100) <= int(rpg_data.STATUS_DEFINITIONS[st["id"]]["wake_on_hit"])
        )
    ]
    if len(kept) != len(statuses):
        defender_after = dict(defender_after)
        defender_after["statuses"] = kept
    return defender_after


def resolve_basic_attack(attacker: dict[str, Any], defender: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    result = calculate_damage(attacker, defender, rng=rng)
    defender_after = dict(defender)
    if not result.get("dodged"):
        defender_after = _wake_on_hit(defender_after, rng)
    defender_after["current_hp"] = max(0, int(defender_after.get("current_hp", defender["current_hp"])) - int(result["damage"]))
    result["defender"] = defender_after
    result["defeated"] = int(defender_after["current_hp"]) <= 0
    return result


def resolve_skill_attack(
    attacker: dict[str, Any],
    defender: dict[str, Any],
    skill_id: str,
    rng: random.Random,
) -> dict[str, Any]:
    skill = get_skill_template(skill_id)
    attacker_after = dict(attacker)
    current_mp = int(attacker_after.get("current_mp", attacker_after["stats"].get("mp", 0)))
    mp_cost = int(skill.get("mp_cost", 0))
    if current_mp < mp_cost:
        return {"ok": False, "reason": "not_enough_mp", "skill": skill}

    attacker_after["current_mp"] = current_mp - mp_cost
    skill_type = skill.get("type", "physical")
    if skill_type == "support":
        # 支援技：自身限时增益（self_buff）+ 回血（power>0 按 MAT×power；E3 百分比/定额）+ 回蓝（E3）。
        heal = 0
        heal_multiplier = float(attacker_after.get("heal_multiplier", 1.0))  # 牧师治疗加成
        buff = skill.get("self_buff")
        if buff:
            attacker_after = apply_buff(
                attacker_after,
                name=str(buff.get("name", skill.get("name", "增益"))),
                mods=dict(buff.get("mods", {})),
                duration=int(buff.get("duration", 3)),
            )
        max_hp = int(attacker_after["stats"].get("hp", 1))
        heal_power = float(skill.get("power", 0.0))
        if heal_power > 0:  # 沿用：MAT×power 治疗
            heal += max(1, int(attacker_after["stats"].get("mat", 0) * heal_power * heal_multiplier))
        if "heal_hp_percent" in skill:  # E3：按最大 HP 百分比回血
            heal += int(max_hp * int(skill["heal_hp_percent"]) / 100 * heal_multiplier)
        if "heal_hp_flat" in skill:  # E3：定额回血（不吃 MAT，物理职可用）
            heal += int(int(skill["heal_hp_flat"]) * heal_multiplier)
        if heal > 0:
            attacker_after["current_hp"] = min(
                max_hp, int(attacker_after.get("current_hp", max_hp)) + heal
            )
        attacker_after = _apply_skill_mp_restore(attacker_after, skill)  # E3：回蓝
        return {
            "ok": True,
            "skill": skill,
            "attacker": attacker_after,
            "defender": defender,
            "support_only": True,
            "heal": heal,
            "buff": buff,
        }

    damage_type = "magical" if skill_type == "magical" else "physical"

    # —— E6：传奇特殊机制（在伤害结算前确定倍率/暴击/穿防修正）——
    power = float(skill.get("power", 1.0))
    crit_mult = 1.5
    defense_mult = 1.0
    extra_mult = 1.0
    special = skill.get("special")
    sargs = skill.get("special_args", {})
    if special == "low_hp_bonus":  # 自身 HP 越低伤害越高
        a_max = max(1, int(attacker_after["stats"].get("hp", 1)))
        if int(attacker_after.get("current_hp", a_max)) / a_max <= float(sargs.get("threshold", 0.3)):
            extra_mult *= float(sargs.get("mult", 1.5))
    elif special == "execute":  # 处决：目标残血时加伤
        d_max = max(1, int(defender["stats"].get("hp", 1)))
        if int(defender.get("current_hp", d_max)) / d_max < float(sargs.get("threshold", 0.5)):
            extra_mult *= float(sargs.get("mult", 1.8))
    elif special == "crit_override":  # 暴击倍率改写
        crit_mult = float(sargs.get("crit_mult", 2.5))
    elif special == "pierce_def":  # 无视部分防御
        defense_mult = float(sargs.get("def_mult", 0.5))
    elif special == "smite_status":  # 对带异常的敌人加伤
        if any(s.get("id") in rpg_data.NEGATIVE_STATUS_IDS for s in defender.get("statuses", [])):
            extra_mult *= float(sargs.get("mult", 1.3))

    # —— E2：多段攻击，每段独立判定暴击/闪避 ——
    hits = max(1, int(skill.get("hits", 1)))
    defender_after = dict(defender)
    total_damage = 0
    any_crit = False
    any_hit = False
    for _ in range(hits):
        if int(defender_after.get("current_hp", 0)) <= 0:
            break
        hit = calculate_damage(
            attacker_after,
            defender_after,
            damage_type=damage_type,
            power_multiplier=power * extra_mult,
            crit_multiplier=crit_mult,
            defense_mult=defense_mult,
            rng=rng,
        )
        if not hit.get("dodged"):
            any_hit = True
            defender_after = _wake_on_hit(defender_after, rng)
        if hit.get("critical"):
            any_crit = True
        dmg = int(hit["damage"])
        total_damage += dmg
        defender_after = dict(defender_after)
        defender_after["current_hp"] = max(0, int(defender_after.get("current_hp", defender["current_hp"])) - dmg)

    # —— E1：伤害技附带自身增益 / 敌方减益（固定值，到期由 tick_statuses 自动撤销）——
    self_buff = skill.get("self_buff")
    if self_buff:
        attacker_after = apply_buff(
            attacker_after,
            name=str(self_buff.get("name", skill.get("name", "增益"))),
            mods=dict(self_buff.get("mods", {})),
            duration=int(self_buff.get("duration", 2)),
        )
    enemy_debuff = skill.get("enemy_debuff")
    if enemy_debuff:
        defender_after = apply_buff(
            defender_after,
            name=str(enemy_debuff.get("name", skill.get("name", "削弱"))),
            mods=dict(enemy_debuff.get("mods", {})),
            duration=int(enemy_debuff.get("duration", 3)),
        )
    attacker_after = _apply_skill_mp_restore(attacker_after, skill)  # E3：回蓝（如安魂曲）

    return {
        "ok": True,
        "skill": skill,
        "attacker": attacker_after,
        "defender": defender_after,
        "damage": total_damage,
        "critical": any_crit,
        "dodged": not any_hit,
        "hits": hits,
        "defeated": int(defender_after["current_hp"]) <= 0,
    }


def _apply_skill_mp_restore(actor: dict[str, Any], skill: dict[str, Any]) -> dict[str, Any]:
    """E3：技能回蓝（heal_mp_self 为按最大 MP 的百分比）。"""
    if "heal_mp_self" not in skill:
        return actor
    actor = dict(actor)
    max_mp = int(actor.get("stats", {}).get("mp", 0))
    mp_back = int(max_mp * int(skill["heal_mp_self"]) / 100)
    actor["current_mp"] = min(max_mp, int(actor.get("current_mp", max_mp)) + mp_back)
    return actor


def escape_rate(character: dict[str, Any], enemy: dict[str, Any]) -> float:
    own_atk = int(character["stats"].get("atk", 0))
    enemy_atk = max(1, int(enemy["stats"].get("atk", 1)))
    luck = int(character.get("random_stats", {}).get("luck", 0))
    return clamp(((own_atk - enemy_atk) / enemy_atk) * 50 + 20 + luck, 0, 100)


def roll_escape(character: dict[str, Any], enemy: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    rate = escape_rate(character, enemy)
    return {"success": rng.random() * 100 < rate, "rate": rate}


def combo_rate(actor: dict[str, Any]) -> float:
    luck = int(actor.get("random_stats", {}).get("luck", 0))
    return clamp(effective_spd(actor) + luck, 0, 100)


def interrupt_rate(fast_actor: dict[str, Any], slow_actor: dict[str, Any]) -> float:
    """快速方抢攻打断慢速方的概率；仅当 fast 的 SPD ≥ slow 的 1.5 倍时才可能发生。

    rate = (fast_spd - slow_spd) * 5 + fast 的幸运，钳制到 [0, 100]。
    """
    fast_spd = effective_spd(fast_actor)
    slow_spd = effective_spd(slow_actor)
    luck = int(fast_actor.get("random_stats", {}).get("luck", 0))
    if fast_spd < slow_spd * 1.5:
        return 0
    return clamp((fast_spd - slow_spd) * 5 + luck, 0, 100)


def reputation_npc_weight_bonus(reputation: int) -> int:
    reputation = int(reputation)
    if reputation <= -500:
        return -15
    if reputation <= -200:
        return -10
    if reputation <= -50:
        return -5
    if reputation <= -1:
        return -2
    if reputation <= 19:
        return 0
    if reputation <= 49:
        return 3
    if reputation <= 199:
        return 8
    if reputation <= 499:
        return 12
    return 15


def random_event_outcome(luck: int, rng: random.Random, reputation: int = 0) -> str:
    reputation = int(reputation)
    positive_rate = clamp(20 + int(luck) + max(-20, min(20, math.floor(reputation / 50))), 0, 99)
    if rng.random() * 100 < positive_rate:
        return "positive"
    negative_rate = clamp(40 - int(luck) + max(-15, min(25, -math.floor(reputation / 50))), 1, 99)
    if rng.random() * 100 < negative_rate:
        return "negative"
    return "neutral"


def npc_initial_affinity(reputation: int, charm: int, rng: random.Random) -> int:
    raw = math.floor(int(reputation) / 10) + int(charm) + rng.randint(-10, 10)
    return clamp_int(raw, -99, 90)


def resolve_social_action(
    action: str,
    character: dict[str, Any],
    affinity: int,
    rng: random.Random,
    *,
    enemy_atk: int | None = None,
) -> dict[str, Any]:
    random_stats = character.get("random_stats", {})
    charm = int(random_stats.get("charm", 0))
    luck = int(random_stats.get("luck", 0))
    roll = rng.randint(1, 20)

    if action == "说服":
        charm_bonus = clamp(charm * 2, -25, 60)
        rate = roll + charm_bonus + int(affinity) * 0.5
        rate = clamp(rate, 0, 100)
        success = rng.random() * 100 < max(0, rate)
        return {"action": action, "roll": roll, "rate": rate, "success": success, "battle": False}

    if action == "欺骗":
        charm_bonus = clamp(charm * 2, -100, 60)
        rate = roll + charm_bonus + int(affinity) * 0.25 + luck
        rate = clamp(rate, 0, 100)
        success = rng.random() * 100 < max(0, rate)
        battle_rate = clamp(40 - luck - charm * 2, 0, 100)
        return {
            "action": action,
            "roll": roll,
            "rate": rate,
            "success": success,
            "battle": (not success) and rng.random() * 100 < battle_rate,
            "battle_rate": battle_rate,
            "charm_delta": 0 if success else -rng.randint(1, 5),
        }

    if action == "威吓":
        own_atk = int(character.get("stats", {}).get("atk", 0))
        target_atk = max(1, int(enemy_atk if enemy_atk is not None else own_atk))
        charm_bonus = clamp(-charm, -20, 20)
        rate = roll + charm_bonus + ((own_atk - target_atk) / target_atk) * 50
        rate = clamp(rate, 0, 100)
        success = rng.random() * 100 < max(0, rate)
        battle_rate = 0 if success else 50
        return {
            "action": action,
            "roll": roll,
            "rate": rate,
            "success": success,
            "battle": (not success) and rng.random() * 100 < battle_rate,
            "battle_rate": battle_rate,
        }

    raise ValueError(f"unknown social action: {action}")


def shop_quality_score(luck: int, rng: random.Random) -> int:
    return clamp_int(30 + int(luck) * 2 + rng.randint(-10, 30), 0, 100)


def shop_quality_from_score(score: int) -> str:
    score = clamp_int(score, 0, 100)
    if score <= 29:
        return "trash"
    if score <= 49:
        return "common"
    if score <= 69:
        return "practical"
    if score <= 89:
        return "rare"
    if score <= 99:
        return "uncommon"
    return "legendary"


def shop_price(base_price: int, quality_score: int, charm: int) -> int:
    multiplier = max(0.5, (int(quality_score) + 100 - int(charm) * 2) / 100)
    return max(1, round(int(base_price) * multiplier))


def items_by_quality(quality: str, *, shop_only: bool = False) -> list[dict[str, Any]]:
    """按品质取可流通道具。shop_only=True 时排除 shop=False 的道具（如职业偏向装备，仅掉落获得）。"""
    return [
        dict(item)
        for item in rpg_data.ITEM_POOLS
        if item.get("quality") == quality
        and item.get("price", 0) > 0
        and not is_special_item(item)
        and (not shop_only or item.get("shop", True))
    ]


def roll_item_by_quality(quality: str, rng: random.Random, *, shop_only: bool = False) -> dict[str, Any] | None:
    candidates = items_by_quality(quality, shop_only=shop_only)
    if not candidates:
        return None
    return dict(rng.choice(candidates))


def roll_special_item(rng: random.Random, *, shop_only: bool = False) -> dict[str, Any] | None:
    candidates = [
        dict(item) for item in rpg_data.ITEM_POOLS
        if is_special_item(item)
        and int(item.get("price", 0)) > 0
        and (not shop_only or item.get("shop", True))
    ]
    if not candidates:
        return None
    return dict(rng.choice(candidates))


def roll_item_from_quality_weights(weights: dict[str, int], rng: random.Random) -> dict[str, Any] | None:
    if not weights:
        return None
    quality = weighted_choice(weights, rng)
    return roll_item_by_quality(quality, rng)


STAT_DISPLAY = {
    "hp": "HP", "atk": "ATK", "def": "DEF", "mat": "MAT", "mdf": "MDF", "mp": "MP", "spd": "SPD",
    "crit": "暴击骰", "resist": "抗性骰", "luck": "幸运", "charm": "魅力",
}
PERM_CORE_POOL = ("hp", "atk", "def", "mat", "mdf")  # 神殿祝福等“随机基础属性”的取值范围


def _effect_amount(spec: Any, rng: random.Random) -> int:
    if isinstance(spec, (list, tuple)):
        return rng.randint(int(spec[0]), int(spec[1]))
    return int(spec)


def _roll_event_item(
    qualities: Sequence[str],
    rng: random.Random,
    *,
    only_consumable: bool = False,
    only_job: bool = False,
) -> dict[str, Any] | None:
    quality = rng.choice(list(qualities))
    candidates = [
        item for item in rpg_data.ITEM_POOLS
        if item.get("quality") == quality and int(item.get("price", 0)) > 0
        and not is_special_item(item)
    ]
    if only_consumable:
        candidates = [i for i in candidates if i.get("type") in ("food", "potion")]
    if only_job:
        candidates = [i for i in candidates if i.get("shop") is False]
    if not candidates:
        return None
    return dict(rng.choice(candidates))


def resolve_event_effects(
    character: dict[str, Any],
    effects: Sequence[dict[str, Any]],
    *,
    chapter: int,
    rng: random.Random,
) -> tuple[dict[str, Any], list[str]]:
    """结算一组事件效果（自动结算类），返回 (更新后的角色, 叙述行)。

    永久属性改动写入 base_stats / base_random_stats / overcap_random 后重算面板；
    限时增益写入 pending_buffs（下一场战斗才施加）。事件不会致死（HP 最低保留 1）。
    """
    lines: list[str] = []
    character.setdefault("base_stats", dict(character.get("stats", {})))
    character.setdefault("base_random_stats", dict(character.get("random_stats", {})))

    for effect in effects:
        kind = effect.get("type")
        stats = character.get("stats", {})

        if kind == "gold":
            amount = _effect_amount(effect["amount"], rng)
            if effect.get("scale_chapter"):
                amount = int(amount * (1 + 0.5 * int(chapter)))
            character["gold"] = int(character.get("gold", 0)) + amount
            lines.append(f"获得 {amount} 金币。")

        elif kind == "gold_loss":
            current = int(character.get("gold", 0))
            if "pct" in effect:
                if current < int(effect.get("min", 0)) and effect.get("fallback_below_min"):
                    character, fb_lines = resolve_event_effects(
                        character, effect["fallback_below_min"], chapter=chapter, rng=rng
                    )
                    lines.extend(fb_lines)
                    continue
                amount = max(int(effect.get("min", 0)), math.ceil(current * int(effect["pct"]) / 100))
            else:
                amount = _effect_amount(effect["amount"], rng)
            amount = min(current, amount)
            character["gold"] = current - amount
            lines.append(f"失去 {amount} 金币。")

        elif kind == "exp":
            amount = _effect_amount(effect["amount"], rng)
            character["run_exp"] = int(character.get("run_exp", 0)) + amount
            character, leveled = add_character_exp(character, amount)
            lines.append(f"获得 {amount} 经验。" + (f"升到 {character['level']} 级！" if leveled else ""))

        elif kind in ("heal_hp_pct", "heal_mp_pct", "heal_full"):
            if kind == "heal_full":
                consumable_effects = {"heal_full": True}
            elif kind == "heal_hp_pct":
                consumable_effects = {"heal_hp_percent": int(effect["pct"])}
            else:
                consumable_effects = {"heal_mp_percent": int(effect["pct"])}
            character, heal_lines = apply_consumable_effects(character, {"effects": consumable_effects}, rng)
            lines.extend(heal_lines)

        elif kind in ("damage_hp_pct_cur", "damage_hp_pct_max", "damage_mp_pct_cur"):
            pct = int(effect["pct"])
            if kind == "damage_mp_pct_cur":
                cur = int(character.get("current_mp", 0))
                dmg = math.ceil(cur * pct / 100)
                character["current_mp"] = max(0, cur - dmg)
                lines.append(f"失去 {dmg} MP。")
            else:
                cur = int(character.get("current_hp", stats.get("hp", 1)))
                base = cur if kind == "damage_hp_pct_cur" else int(stats.get("hp", cur))
                dmg = math.ceil(base * pct / 100)
                character["current_hp"] = max(1, cur - dmg)  # 事件不致死
                lines.append(f"失去 {dmg} HP。")

        elif kind == "item":
            qualities = effect["by_chapter"][min(int(chapter), len(effect["by_chapter"]) - 1)] if "by_chapter" in effect else effect["qualities"]
            item = _roll_event_item(
                qualities, rng,
                only_consumable=bool(effect.get("only_consumable")),
                only_job=bool(effect.get("only_job")),
            )
            if item is None:
                lines.append("似乎什么也没找到。")
            else:
                ok, _reason = add_item_to_inventory(character, item["id"])
                lines.append(f"获得道具：{item['name']}。" if ok else f"发现了 {item['name']}，但背包已满，错失了。")

        elif kind == "perm_core":
            stat = rng.choice(PERM_CORE_POOL) if effect["stat"] == "random" else effect["stat"]
            amount = _effect_amount(effect["amount"], rng)
            perm = _ensure_perm_core_bonus(character)
            perm[stat] = int(perm.get(stat, 0)) + amount
            character = recompute_character_stats(character)
            lines.append(f"{STAT_DISPLAY.get(stat, stat)} 永久 {amount:+d}。")

        elif kind == "perm_core_all":
            amount = _effect_amount(effect["amount"], rng)
            perm = _ensure_perm_core_bonus(character)
            for stat in PERM_CORE_POOL:
                perm[stat] = int(perm.get(stat, 0)) + amount
            character = recompute_character_stats(character)
            lines.append(f"全基础属性 永久 {amount:+d}。")

        elif kind == "perm_dice":
            stat = rng.choice(RANDOM_STAT_KEYS) if effect["stat"] == "random" else effect["stat"]
            amount = _effect_amount(effect["amount"], rng)
            character["base_random_stats"][stat] = int(character["base_random_stats"].get(stat, 0)) + amount
            character = recompute_character_stats(character)
            lines.append(f"{STAT_DISPLAY.get(stat, stat)} 永久 {amount:+d}。")

        elif kind == "overcap_dice":
            stat = effect["stat"]
            amount = _effect_amount(effect["amount"], rng)
            character.setdefault("overcap_random", {})
            character["overcap_random"][stat] = int(character["overcap_random"].get(stat, 0)) + amount
            character = recompute_character_stats(character)
            lines.append(f"{STAT_DISPLAY.get(stat, stat)} {amount:+d}（可突破上限）。")

        elif kind == "cleanse":
            statuses = [s for s in character.get("statuses", []) if s.get("id") not in rpg_data.NEGATIVE_STATUS_IDS]
            character["statuses"] = statuses
            lines.append("清除了所有负面状态。")

        elif kind == "pending_buff":
            character.setdefault("pending_buffs", []).append(
                {"name": effect["name"], "mods": dict(effect["mods"]), "duration": int(effect["duration"])}
            )
            lines.append(f"获得增益【{effect['name']}】（下一场战斗生效）。")

        elif kind == "lose_equipment":
            equipment = character.get("equipment", [])
            if equipment:
                lost = equipment.pop(rng.randrange(len(equipment)))
                character = recompute_character_stats(character)
                try:
                    lost_name = get_item_template(lost["id"])["name"]
                except ValueError:
                    lost_name = lost["id"]
                lines.append(f"失去了装备：{lost_name}。")
            elif effect.get("fallback"):
                character, fb_lines = resolve_event_effects(character, effect["fallback"], chapter=chapter, rng=rng)
                lines.extend(fb_lines)

        elif kind == "lose_consumable":
            consumables = list_consumables(character)
            if consumables:
                _consume_one(character, rng.choice(consumables))
                lines.append("背包里的一件消耗品不见了。")
            elif effect.get("fallback"):
                character, fb_lines = resolve_event_effects(character, effect["fallback"], chapter=chapter, rng=rng)
                lines.extend(fb_lines)

        elif kind == "run_label":
            character.setdefault("run_statuses", []).append(str(effect["label"]))
            lines.append(f"获得状态【{effect['label']}】。")

        elif kind == "nothing":
            if effect.get("text"):
                lines.append(str(effect["text"]))

        elif kind == "gamble_gold":
            current = int(character.get("gold", 0))
            bet = int(current * float(effect.get("fraction", 0.3)))
            if bet <= 0:
                lines.append("你没有足够的金币下注。")
            elif rng.random() < 0.5:
                win = bet * (int(effect.get("win_mult", 2)) - 1)
                character["gold"] = current + win
                lines.append(f"赌赢了！净赚 {win} 金币。")
            else:
                character["gold"] = current - bet
                lines.append(f"赌输了，失去 {bet} 金币。")

        elif kind == "random_effect":
            chosen = rng.choice(effect["options"])
            sub_effects = chosen if isinstance(chosen, list) else [chosen]
            character, sub_lines = resolve_event_effects(character, sub_effects, chapter=chapter, rng=rng)
            lines.extend(sub_lines)

        elif kind == "reroll_dice":
            character["base_random_stats"] = roll_random_stats(rng)
            character = recompute_character_stats(character)
            rolled = character["random_stats"]
            lines.append(
                f"重掷骰子属性：暴击骰{rolled['crit']} 抗性骰{rolled['resist']} 幸运{rolled['luck']} 魅力{rolled['charm']}。"
            )

        elif kind == "craft_consumable":
            consumables = list_consumables(character)
            if not consumables:
                lines.append("你没有可用于合成的消耗品。")
            else:
                entry = rng.choice(consumables)
                original = get_item_template(entry["id"])
                _consume_one(character, entry)
                if rng.random() < 0.6:
                    order = ["trash", "common", "practical", "rare", "uncommon", "legendary"]
                    next_index = min(len(order) - 1, order.index(original.get("quality", "common")) + 1)
                    product = _roll_event_item([order[next_index]], rng, only_consumable=True)
                    if product is None:
                        lines.append("合成成功，但没有合适的产物。")
                    else:
                        ok, _reason = add_item_to_inventory(character, product["id"])
                        lines.append(f"合成成功！获得 {product['name']}。" if ok else f"合成出 {product['name']}，但背包已满。")
                else:
                    lines.append(f"合成失败，{original['name']} 化为了灰烬。")

        elif kind == "shop_discount":
            character["shop_discount"] = int(character.get("shop_discount", 0)) + int(effect["amount"])
            lines.append(f"此后商店价格 -{int(effect['amount'])}%（本局可叠加）。")

        elif kind == "forest_song":
            if rng.random() < 0.5:
                if rng.random() < 0.3:  # 天选之子（仅此处可触发）
                    character, sub_lines = resolve_event_effects(
                        character,
                        [{"type": "overcap_dice", "stat": "luck", "amount": 20}, {"type": "run_label", "label": "天选之子"}],
                        chapter=chapter, rng=rng,
                    )
                    lines.append("循声而去，你在清泉边饮下泉水，周身萦绕金光……")
                    lines.extend(sub_lines)
                else:
                    sub_evt = rng.choice(rpg_data.EVENT_POOLS["positive"])
                    character, sub_lines = resolve_event_effects(character, sub_evt["effects"], chapter=chapter, rng=rng)
                    lines.append(f"循声而去，触发了【{sub_evt['name']}】。")
                    lines.extend(sub_lines)
            else:
                candidates = [e for e in rpg_data.EVENT_POOLS["negative"] if not e.get("once")]
                sub_evt = rng.choice(candidates)
                character, sub_lines = resolve_event_effects(character, sub_evt["effects"], chapter=chapter, rng=rng)
                lines.append(f"循声而去，却遭遇了【{sub_evt['name']}】。")
                lines.extend(sub_lines)

        elif kind == "consume_one":  # 作为代价消耗一件随机消耗品
            consumables = list_consumables(character)
            if consumables:
                _consume_one(character, rng.choice(consumables))

        elif kind == "riddle":
            if rng.randint(1, 100) <= int(effect.get("correct_chance", 50)):
                lines.append("你答对了！")
                character, sub_lines = resolve_event_effects(character, effect["correct"], chapter=chapter, rng=rng)
            else:
                lines.append("你答错了……")
                character, sub_lines = resolve_event_effects(character, effect["wrong"], chapter=chapter, rng=rng)
            lines.extend(sub_lines)

        elif kind == "friendly_battle":
            luck = int(character.get("random_stats", {}).get("luck", 0))
            if rng.randint(1, 100) <= int(clamp(50 + luck, 5, 95)):
                lines.append("切磋获胜！")
                character, sub_lines = resolve_event_effects(character, effect["win"], chapter=chapter, rng=rng)
            else:
                lines.append("切磋落败，但也有所收获。")
                character, sub_lines = resolve_event_effects(character, effect["lose"], chapter=chapter, rng=rng)
            lines.extend(sub_lines)

        elif kind == "sell_one":
            inventory = character.get("inventory", [])
            sellable = [e for e in inventory if int(get_item_template(e["id"]).get("price", 0)) > 0]
            if not sellable:
                lines.append("你没有可出售的道具。")
            else:
                entry = rng.choice(sellable)
                template = get_item_template(entry["id"])
                price = max(1, round(int(template["price"]) * float(effect.get("mult", 0.6))))
                _consume_one(character, entry)
                character["gold"] = int(character.get("gold", 0)) + price
                lines.append(f"卖出 {template['name']}，获得 {price} 金币。")

    return character, lines


def _consume_one(character: dict[str, Any], entry: dict[str, Any]) -> None:
    """从背包扣除一件指定道具（数量 -1，归零则移除）。"""
    quantity = int(entry.get("quantity", 1)) - 1
    if quantity <= 0:
        character["inventory"].remove(entry)
    else:
        entry["quantity"] = quantity


def generate_shop_stock(
    luck: int,
    charm: int,
    rng: random.Random,
    *,
    count: int = 3,
    discount: int = 0,
) -> list[dict[str, Any]]:
    stock: list[dict[str, Any]] = []
    for _ in range(count):
        score = shop_quality_score(luck, rng)
        quality = shop_quality_from_score(score)
        item = roll_special_item(rng, shop_only=True) if rng.randint(1, 100) <= rpg_data.SPECIAL_ITEM_SHOP_CHANCE else None
        if item is None:
            item = roll_item_by_quality(quality, rng, shop_only=True)
        if item is None:
            item = dict(
                rng.choice(
                    [
                        item for item in rpg_data.ITEM_POOLS
                        if item.get("price", 0) > 0 and item.get("shop", True) and not is_special_item(item)
                    ]
                )
            )
        item["quality_score"] = score
        price = shop_price(int(item["price"]), score, charm)
        if discount:  # 商人难题等带来的本局持久折扣
            price = max(1, round(price * (1 - int(discount) / 100)))
        item["final_price"] = price
        stock.append(item)
    return stock


def quality_median_price(quality: str) -> int:
    prices = sorted(
        int(item["price"]) for item in rpg_data.ITEM_POOLS
        if item.get("quality") == quality and int(item.get("price", 0)) > 0 and item.get("shop", True)
        and not is_special_item(item)
    )
    return prices[len(prices) // 2] if prices else 10


def roll_blind_item(quality: str, rng: random.Random) -> dict[str, Any] | None:
    """盲盒购买：买下后才随机出该稀有度的具体道具。"""
    candidates = [
        item for item in rpg_data.ITEM_POOLS
        if item.get("quality") == quality and int(item.get("price", 0)) > 0 and item.get("shop", True)
        and not is_special_item(item)
    ]
    return dict(rng.choice(candidates)) if candidates else None


def generate_npc_shop(
    rng: random.Random,
    *,
    types: Sequence[str] | None = None,
    qualities: Sequence[str] | None = None,
    count: int = 3,
    price_mult: float = 1.0,
    blind: bool = False,
) -> list[dict[str, Any]]:
    """NPC 专属小商店：按类型/品质过滤，定价 = 基础价 × price_mult（不走幸运品质卷）。

    blind=True 时只生成“稀有度槽位”：只显示稀有度、价格取该稀有度中位价，买下后再随机具体道具。
    """
    if blind:
        choices = list(qualities) if qualities else ["common", "practical", "rare"]
        stock: list[dict[str, Any]] = []
        for _ in range(int(count)):
            quality = rng.choice(choices)
            stock.append({
                "blind": True,
                "quality": quality,
                "name": "？？？",
                "description": "买下后才知道是什么。",
                "final_price": max(1, round(quality_median_price(quality) * float(price_mult))),
            })
        return stock

    pool = [
        item for item in rpg_data.ITEM_POOLS
        if int(item.get("price", 0)) > 0 and item.get("shop", True) and not is_special_item(item)
    ]
    if types:
        pool = [item for item in pool if item.get("type") in set(types)]
    if qualities:
        pool = [item for item in pool if item.get("quality") in set(qualities)]
    stock: list[dict[str, Any]] = []
    for _ in range(int(count)):
        if not pool:
            break
        item = dict(rng.choice(pool))
        item["quality_score"] = 0
        item["final_price"] = max(1, round(int(item["price"]) * float(price_mult)))
        stock.append(item)
    return stock


def enemy_reward(rank: str, rng: random.Random) -> dict[str, Any]:
    profile = rpg_data.ENEMY_RANKS[rank]
    item = None
    if rng.randint(1, 100) <= int(profile["drop_chance"]):
        item = roll_item_from_quality_weights(profile["drop_quality_weights"], rng)
    return {
        "exp": int(profile["exp_reward"]),
        "gold": int(profile["gold_reward"]),
        "item": item,
    }


def boss_reward(boss_id: str, rng: random.Random) -> dict[str, Any]:
    boss = get_boss_template(boss_id)
    reward = dict(boss["reward"])
    item = roll_item_from_quality_weights(dict(reward.get("drop_quality_weights", {})), rng)
    carry_out = list(reward.get("carry_out", []))
    keepsake_id = reward.get("keepsake_id")
    if keepsake_id and rng.randint(1, 100) <= int(reward.get("keepsake_chance", 0)):
        carry_out.append(str(keepsake_id))
    return {
        "exp": int(reward["exp"]),
        "gold": int(reward["gold"]),
        "item": item,
        "carry_out": carry_out,
    }


def adjusted_node_weights_for_reputation(chapter: dict[str, Any], reputation: int) -> dict[str, int]:
    weights = dict(chapter["node_weights"])
    npc_bonus = reputation_npc_weight_bonus(reputation)
    weights["npc"] = max(1, int(weights.get("npc", 0)) + npc_bonus)
    if npc_bonus < 0:
        weights["battle"] = int(weights.get("battle", 0)) + abs(npc_bonus) // 2
        weights["mystery"] = int(weights.get("mystery", 0)) + abs(npc_bonus) // 2
    elif npc_bonus > 0:
        weights["battle"] = max(1, int(weights.get("battle", 0)) - npc_bonus // 3)
    return weights


def generate_node_choices(chapter: dict[str, Any], rng: random.Random, reputation: int = 0) -> list[dict[str, Any]]:
    choice_count = rng.randint(2, 3)
    weights = adjusted_node_weights_for_reputation(chapter, reputation)
    choices: list[dict[str, Any]] = []
    for index in range(1, choice_count + 1):
        node_type = weighted_choice(weights, rng)
        choices.append({"index": index, "type": node_type})
    return choices


def generate_run_map(rng: random.Random, reputation: int = 0) -> dict[str, Any]:
    chapters: list[dict[str, Any]] = []
    for chapter in rpg_data.CHAPTER_DEFINITIONS:
        floor_count = rng.randint(int(chapter["min_floors"]), int(chapter["max_floors"]))
        floors = [
            {"index": floor_index, "choices": generate_node_choices(chapter, rng, reputation)}
            for floor_index in range(1, floor_count + 1)
        ]
        floors.append(
            {
                "index": floor_count + 1,
                "choices": [{"index": 1, "type": "boss", "boss_id": chapter["boss_id"]}],
            }
        )
        chapters.append(
            {
                "id": chapter["id"],
                "name": chapter["name"],
                "floors": floors,
                "boss_id": chapter["boss_id"],
            }
        )
    return {"chapters": chapters}


def apply_rest(character: dict[str, Any]) -> dict[str, Any]:
    updated = dict(character)
    stats = updated["stats"]
    updated["current_hp"] = min(
        int(stats["hp"]),
        int(updated.get("current_hp", stats["hp"])) + math.ceil(int(stats["hp"]) * 0.30),
    )
    updated["current_mp"] = min(
        int(stats["mp"]),
        int(updated.get("current_mp", stats["mp"])) + math.ceil(int(stats["mp"]) * 0.40),
    )
    return updated


def calculate_pet_assist_damage(
    pet_attack: int,
    pet_level: int,
    affection: int,
    enemy_defense: int,
    rng: random.Random,
) -> int:
    actual_attack = min(999, int(pet_attack * (1.5 ** int(pet_level))))
    raw = (
        (actual_attack * actual_attack)
        / max(1, int(enemy_defense))
        * (clamp(int(affection), 0, 100) / 100)
        * rng.uniform(0.99, 1.01)
    )
    return max(0, int(raw))


def calculate_final_rewards(
    character: dict[str, Any],
    *,
    result: str,
    carry_out_item_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    multiplier = 1.0 if result == "victory" else 0.5
    if result == "victory":
        multiplier *= float(character.get("final_reward_multiplier", 1.0))
    elif float(character.get("final_reward_multiplier", 1.0)) >= 2.0:
        multiplier = 1.0
    run_exp = int(character.get("run_exp", 0))
    if run_exp <= 0:
        run_exp = int(character.get("exp", 0))
    run_gold = int(character.get("gold", 0))
    charm = int(character.get("random_stats", {}).get("charm", 0))
    outside_exp = math.floor((run_exp + run_gold) * multiplier)
    outside_reputation = math.floor(charm * multiplier)
    return {
        "result": result,
        "multiplier": multiplier,
        "run_exp": run_exp,
        "run_gold": run_gold,
        "charm": charm,
        "outside_exp": outside_exp,
        "outside_reputation": outside_reputation,
        "carry_out_items": list(carry_out_item_ids or []),
    }
