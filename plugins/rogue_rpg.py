"""QQ command entry for the fantasy roguelike RPG."""

from __future__ import annotations

import random
from datetime import datetime
from typing import Any

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message, MessageEvent
from nonebot.params import CommandArg

from . import rpg_achievements, rpg_ai, rpg_data, rpg_engine, rpg_renderer
from .database import (
    add_rpg_player_items,
    create_rpg_run,
    decode_rpg_run_state,
    finish_rpg_run,
    get_active_rpg_run,
    get_rpg_player,
    list_rpg_achievements,
    list_rpg_player_items,
    rpg_player_exp_to_next_level,
    save_rpg_run_state,
    set_rpg_player_gm_welcome,
    unlock_rpg_achievement,
)
from .message_utils import reply_message, should_ignore_group_message


# 各状态下 /返回 的上一级目标。确认对话改用独立的 "confirm" 伪状态，
# 取消时回退到 confirm_action["restore"]，不再复用本表（修掉旧的误回退 bug）。
RETURN_TARGETS = {
    "standard_menu": "mode_select",
    "class_select": "standard_menu",
    "stat_pending": "class_select",
    "stat_assigned": "class_select",
    "skill_select": "battle",
    "item_select": "battle",
    # 进入商店/NPC 节点即视为已选定该节点，不允许 /返回 回到本层选项重选
    # （否则等于免费偷看 + 换节点）。离开商店用 /退出商店，NPC 用事件里的“离开”选项。
}

# 不允许换装 / 普通导航的「战斗相关」状态
BATTLE_STATUSES = {"battle", "skill_select", "item_select"}

# 仍处于「建号/出发前」的状态；只有这些状态才允许重建角色 / 开局，
# 避免冒险中途用 /创建角色、/开始冒险 等指令重置存档。
SETUP_STATUSES = {"standard_menu", "class_select", "stat_pending", "stat_assigned"}

CLASS_ALIASES = {
    "战士": "warrior",
    "法师": "mage",
    "游侠": "ranger",
    "牧师": "cleric",
    "盗贼": "rogue",
    "吟游诗人": "bard",
    "warrior": "warrior",
    "mage": "mage",
    "ranger": "ranger",
    "cleric": "cleric",
    "rogue": "rogue",
    "bard": "bard",
}


def _rng_for_run(state: dict[str, Any], salt: str = "") -> random.Random:
    return rpg_engine.make_rng(f"{state.get('seed', '')}:{salt}")


def _sync_inventory(state: dict[str, Any] | None) -> dict[str, Any] | None:
    """让 state['inventory'] 与 character['inventory'] 指向同一份数据，避免两边漂移。

    背包的唯一真相是 character['inventory']；顶层 state['inventory'] 仅作镜像存档用。
    """
    if state is not None and isinstance(state.get("character"), dict):
        state["inventory"] = state["character"].setdefault("inventory", state.get("inventory", []))
    return state


def _load_state(user_id: int) -> dict[str, Any] | None:
    row = get_active_rpg_run(user_id)
    if row is None:
        return None
    return _sync_inventory(decode_rpg_run_state(row))


def _save_state(state: dict[str, Any]) -> dict[str, Any]:
    character = state.get("character", {})
    inventory = character.get("inventory", []) if isinstance(character, dict) else []
    row = save_rpg_run_state(
        int(state["id"]),
        status=str(state["status"]),
        chapter=int(state.get("chapter", 0)),
        floor=int(state.get("floor", 0)),
        character=character,
        map_data=state.get("map", {}),
        inventory=inventory,  # 始终镜像 character 的背包，保持两个 JSON 列一致
        flags=state.get("flags", {}),
    )
    if row is None:
        raise RuntimeError("保存 RPG 冒险状态失败")
    return _sync_inventory(decode_rpg_run_state(row))


ADD_ITEM_FAIL_REASONS = {
    "backpack_full": "背包已满",
    "duplicate_equipment": "同名装备只能持有一件",
    "duplicate_special": "同名特殊道具只能持有一件",
    "stack_full": "该道具已堆满",
}


def _append_inventory(character: dict[str, Any], item_id: str) -> bool:
    ok, _reason = rpg_engine.add_item_to_inventory(character, item_id)
    if ok:
        _sync_special_passives(character)
    return ok


def _consume_entry(character: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    item = rpg_engine.get_item_template(entry["id"])
    quantity = int(entry.get("quantity", 1)) - 1
    if quantity <= 0:
        character["inventory"].remove(entry)
    else:
        entry["quantity"] = quantity
    return item


def _is_outside_collectible(item: dict[str, Any]) -> bool:
    return item.get("quality") == "special" or item.get("type") in {"special", "keepsake", "certificate"}


def _outside_dimension_pocket_bonus(user_id: int) -> int:
    return sum(
        int(row["quantity"]) for row in list_rpg_player_items(user_id)
        if row["item_id"] == "dimension_pocket"
    )


def _outside_genesis_multiplier(user_id: int) -> float:
    count = sum(
        int(row["quantity"]) for row in list_rpg_player_items(user_id)
        if row["item_id"] == "genesis_record"
    )
    return min(1.6, 1.0 + 0.2 * count)


def _sync_special_passives(character: dict[str, Any], user_id: int | None = None) -> dict[str, Any]:
    outside_bonus = _outside_dimension_pocket_bonus(user_id) if user_id is not None else int(character.get("outside_backpack_slot_bonus", 0))
    local_bonus = 0
    for entry in character.get("inventory", []):
        if entry.get("id") == "dimension_pocket":
            local_bonus += int(entry.get("quantity", 1))
    total_bonus = min(
        rpg_data.MAX_BACKPACK_SLOTS_WITH_BONUS - rpg_data.MAX_BACKPACK_SLOTS,
        max(0, outside_bonus + local_bonus),
    )
    character["outside_backpack_slot_bonus"] = max(0, outside_bonus)
    character["backpack_slot_bonus"] = total_bonus
    if user_id is not None:
        character["final_reward_multiplier"] = max(
            float(character.get("final_reward_multiplier", 1.0)),
            _outside_genesis_multiplier(user_id),
        )
    return character


def _has_item(character: dict[str, Any], item_id: str) -> bool:
    return any(entry.get("id") == item_id for entry in character.get("inventory", []))


def _consume_item_by_id(character: dict[str, Any], item_id: str) -> bool:
    for entry in list(character.get("inventory", [])):
        if entry.get("id") == item_id:
            _consume_entry(character, entry)
            _sync_special_passives(character)
            return True
    return False


def _special_shop_discount(character: dict[str, Any]) -> int:
    return 20 if _has_item(character, "merchant_token") else 0


def _render_current_floor_reveal(state: dict[str, Any], *, details: bool = False) -> str:
    lines = ["当前层情报："]
    for choice in _current_floor_choices(state):
        node_type = choice["type"]
        node_name = rpg_renderer.NODE_NAMES.get(node_type, node_type)
        if node_type == "boss":
            boss = rpg_engine.get_boss_template(choice["boss_id"])
            node_name = f"Boss：{boss['name']} Lv.{boss['level']}"
        elif details and node_type in {"battle", "elite"}:
            rank = "精英或更强" if node_type == "elite" else "普通敌人"
            node_name = f"{node_name}（{rank}）"
        lines.append(f"{choice['index']}：{node_name}")
    return "\n".join(lines)


def _render_enemy_details(enemy: dict[str, Any]) -> str:
    stats = enemy.get("stats", {})
    return (
        f"【{enemy.get('name', '敌人')}】Lv.{enemy.get('level', '?')} {enemy.get('rank_name', '')}\n"
        f"HP {enemy.get('current_hp', stats.get('hp', 0))}/{stats.get('hp', 0)} | MP {enemy.get('current_mp', stats.get('mp', 0))}/{stats.get('mp', 0)}\n"
        f"ATK {stats.get('atk', 0)} | DEF {stats.get('def', 0)} | MAT {stats.get('mat', 0)} | MDF {stats.get('mdf', 0)} | SPD {stats.get('spd', 0)}\n"
        f"技能：{'、'.join(enemy.get('skills', [])) or '无'}"
    )


def _learn_random_skill(character: dict[str, Any], rng: random.Random) -> tuple[dict[str, Any], str]:
    known = set(character.get("skills", []))
    class_id = character.get("class_id")
    candidates = [
        skill for skill in rpg_data.BASE_SKILLS
        if not skill.get("innate")
        and skill["id"] not in known
        and skill.get("class_req") in (None, class_id)
    ]
    if not candidates:
        return character, "没有可学习的新技能。"
    skill = rng.choice(candidates)
    ok, reason = rpg_engine.learn_skill(character, skill["id"])
    if ok:
        return character, f"学会了技能【{skill['name']}】。"
    if reason == "slots_full":
        return character, f"技能栏已满，无法学习【{skill['name']}】。"
    return character, "未能学习新技能。"


def _handle_active_special_item(
    state: dict[str, Any],
    entry: dict[str, Any],
    item: dict[str, Any],
    rng: random.Random,
) -> str | None:
    if not rpg_engine.is_active_special_item(item):
        return None
    effect = rpg_engine.special_effect_id(item)
    character = state["character"]
    consume = True
    lines = [f"使用了 {item['name']}。"]

    if effect == "reveal_nodes":
        lines.append(_render_current_floor_reveal(state))
    elif effect == "reveal_details":
        lines.append(_render_current_floor_reveal(state, details=True))
    elif effect == "inspect_enemy":
        enemy = state.get("flags", {}).get("enemy")
        if not enemy:
            return "这个道具需要在战斗中使用。"
        lines.append(_render_enemy_details(enemy))
    elif effect == "battle_escape":
        enemy = state.get("flags", {}).get("enemy")
        if not enemy:
            return "这个道具需要在战斗中使用。"
        if enemy.get("rank") == "boss":
            return "Boss 战无法使用传送卷轴逃跑。"
        state["flags"].pop("enemy", None)
        state["flags"].pop("bounty_reward", None)
        state["character"] = _clear_combat_statuses(character)
        _consume_entry(state["character"], entry)
        _sync_special_passives(state["character"])
        return "\n".join(lines + ["传送成功，你脱离了战斗。", _render_current_floor_or_finish(state)])
    elif effect == "learn_random_skill":
        character, line = _learn_random_skill(character, rng)
        state["character"] = character
        lines.append(line)
    elif effect in {"abyss_contract", "reroll_random_keep_best", "final_reward_multiplier"}:
        character, eff_lines = rpg_engine.apply_consumable_effects(character, item, rng)
        state["character"] = character
        lines.extend(eff_lines)
    elif effect == "skip_floor":
        chapter_key = str(state.get("chapter", 0))
        used = state["flags"].setdefault("world_key_used_chapters", [])
        if chapter_key in used:
            return "世界之钥本章已经使用过了。"
        used.append(chapter_key)
        consume = False
        state["flags"].pop("enemy", None)
        state["character"] = _clear_combat_statuses(character)
        return "\n".join(lines + ["世界之钥打开了捷径。", _render_current_floor_or_finish(state)])
    elif effect == "steal_next_enemy_skill":
        state["flags"]["soul_gem_active"] = True
        lines.append("灵魂宝石开始发光：下一次击杀敌人时会尝试夺取一个技能。")
    elif effect == "rewind_round":
        return "时光沙漏需要战斗回合快照，当前版本暂未接入，不会消耗。"
    else:
        return f"{item['name']} 的特殊效果暂未接入。"

    if consume:
        _consume_entry(state["character"], entry)
        _sync_special_passives(state["character"])
    _save_state(state)
    return "\n".join(lines)


def _try_special_revive(state: dict[str, Any]) -> str | None:
    character = state["character"]
    if int(character.get("current_hp", 0)) > 0:
        return None
    candidates = [
        ("phoenix_feather", "不死鸟羽毛", 50, "phoenix_feather_used"),
        ("life_anchor", "生命锚", 30, "life_anchor_used"),
    ]
    for item_id, name, heal_pct, flag in candidates:
        if state["flags"].get(flag) or not _has_item(character, item_id):
            continue
        max_hp = max(1, int(character.get("stats", {}).get("hp", 1)))
        character["current_hp"] = max(1, max_hp * heal_pct // 100)
        state["flags"][flag] = True
        return f"{name}触发：你从濒死中回归，回复 {character['current_hp']} HP。"
    return None


def _enemy_followup_after_item(state: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    enemy = state.get("flags", {}).get("enemy")
    if not enemy:
        return {"outcome": "continue", "lines": []}
    character = state["character"]
    action = rpg_engine.choose_enemy_action(enemy, rng)
    enemy_after, character_after, lines = _execute_action(enemy, character, action, enemy.get("name", "敌人"), "你", rng)
    state["flags"]["enemy"] = enemy_after
    state["character"] = character_after
    outcome = "player_defeated" if int(character_after.get("current_hp", 0)) <= 0 else "continue"
    if outcome == "player_defeated":
        revive_line = _try_special_revive(state)
        if revive_line:
            lines.append(revive_line)
            outcome = "continue"
    return {"outcome": outcome, "lines": lines, "item_used": False}


def _collect_outside_item_ids(character: dict[str, Any], carry_out: list[str]) -> list[str]:
    item_ids = list(carry_out)
    for entry in character.get("inventory", []):
        try:
            item = rpg_engine.get_item_template(entry["id"])
        except ValueError:
            continue
        if _is_outside_collectible(item):
            item_ids.extend([str(entry["id"])] * max(1, int(entry.get("quantity", 1))))
    return item_ids


def _fallback_background(character: dict[str, Any]) -> str:
    return (
        f"你曾是边境传闻里的{character['class_name']}，在一封无名来信的召唤下踏入秘境。"
        "晨雾散开时，第一道岔路已经等在脚边。"
    )


def _resolve_class_id(text: str) -> str | None:
    value = text.strip()
    if value.isdigit():
        index = int(value) - 1
        if 0 <= index < len(rpg_data.STANDARD_CLASSES):
            return rpg_data.STANDARD_CLASSES[index]["id"]
    return CLASS_ALIASES.get(value)


def _current_floor_choices(state: dict[str, Any]) -> list[dict[str, Any]]:
    chapter = state["map"]["chapters"][int(state.get("chapter", 0))]
    floor = chapter["floors"][int(state.get("floor", 0))]
    return list(floor["choices"])


def _advance_floor(state: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    chapter_index = int(state.get("chapter", 0))
    floor_index = int(state.get("floor", 0)) + 1
    chapters = state["map"]["chapters"]

    if chapter_index >= len(chapters):
        return state, "victory"

    if floor_index < len(chapters[chapter_index]["floors"]):
        state["floor"] = floor_index
        state["status"] = "floor_select"
        return state, None

    chapter_index += 1
    if chapter_index >= len(chapters):
        return state, "victory"

    state["chapter"] = chapter_index
    state["floor"] = 0
    state["status"] = "floor_select"
    return state, None


def _ach_counters(state: dict[str, Any]) -> dict[str, Any]:
    """取（必要时初始化）本局成就计数器，挂在 state['flags']['ach'] 上随存档持久化。"""
    return state.setdefault("flags", {}).setdefault("ach", rpg_achievements.new_run_counters())


def _record_social_attempt(state: dict[str, Any], action: str, success: bool) -> None:
    """记录一次社交判定（说服/欺骗/威吓）的成败，用于社交类成就。"""
    key = {"说服": "persuade", "欺骗": "deceive", "威吓": "intimidate"}.get(action)
    if key is None:
        return
    counter = _ach_counters(state).setdefault(key, {"n": 0, "ok": 0})
    counter["n"] += 1
    if success:
        counter["ok"] += 1


def _evaluate_achievements(state: dict[str, Any], result: str) -> list[str]:
    """一局结束时比对全部成就，落库首次解锁的，返回用于提示的成就名列表。

    须在 finish_rpg_run / add_rpg_player_items 之后调用：
    #1~#4 依赖刷新后的累计通关数，#22 依赖刚带出的纪念物。
    """
    user_id = int(state["user_id"])
    character = state.get("character", {})
    random_stats = character.get("random_stats", {})
    player = get_rpg_player(user_id)
    owned_keepsakes = {row["item_id"] for row in list_rpg_player_items(user_id)}
    ctx = {
        "result": result,
        "won": result == "victory",
        "wins": int(player["wins"]),
        "charm": int(random_stats.get("charm", 0)),
        "luck": int(random_stats.get("luck", 0)),
        # 旧版进行中的存档没记 start_luck，给个大值避免误判隐藏成就 #5
        "start_luck": int(state.get("flags", {}).get("start_luck", 999)),
        "run_statuses": list(character.get("run_statuses", [])),
        "ach": _ach_counters(state),
        "owned_keepsakes": owned_keepsakes,
    }
    already = list_rpg_achievements(user_id)
    unlocked_names: list[str] = []
    for ach_id in rpg_achievements.evaluate(ctx):
        if ach_id in already:
            continue
        if unlock_rpg_achievement(user_id, ach_id):
            unlocked_names.append(rpg_achievements.ACHIEVEMENTS_BY_ID[ach_id]["name"])
    return unlocked_names


def _finish_run(state: dict[str, Any], result: str) -> str:
    character = state.get("character", {})
    carry_out = state.get("flags", {}).get("carry_out_items", [])
    outside_item_ids = _collect_outside_item_ids(character, carry_out) if result == "victory" else []
    final_rewards = rpg_engine.calculate_final_rewards(
        character,
        result=result,
        carry_out_item_ids=outside_item_ids,
    )
    finished_run = finish_rpg_run(
        int(state["id"]),
        result,
        exp_amount=int(final_rewards["outside_exp"]),
        reputation_delta=int(final_rewards["outside_reputation"]),
        won=result == "victory",
        died=result == "death",
    )
    if finished_run is None:
        return "本局已经完成结算，请发送 /冒险 开始新的旅程。"
    add_rpg_player_items(int(state["user_id"]), outside_item_ids)
    player = get_rpg_player(int(state["user_id"]))
    final_rewards["outside_player"] = {
        "level": int(player["level"]),
        "exp": int(player["exp"]),
        "next_exp": rpg_player_exp_to_next_level(int(player["level"])),
        "reputation": int(player["reputation"]),
        "title": str(player["title"]),
    }
    state["_run_finished"] = result  # 供异步层检测本局是否刚结束（用于 AI 结局旁白）
    text = rpg_renderer.render_final_rewards(final_rewards)
    unlocked = _evaluate_achievements(state, result)
    if unlocked:
        text += "\n\n🏆 解锁成就：" + "、".join(unlocked)
    return text


def _render_current_floor_or_finish(state: dict[str, Any]) -> str:
    state, result = _advance_floor(state)
    if result is not None:
        return _finish_run(state, result)
    _save_state(state)
    return rpg_renderer.render_floor_choices(state["map"], int(state["chapter"]), int(state["floor"]))


def _grant_reward(character: dict[str, Any], reward: dict[str, Any]) -> tuple[dict[str, Any], int]:
    character["gold"] = int(character.get("gold", 0)) + int(reward.get("gold", 0))
    character["run_exp"] = int(character.get("run_exp", 0)) + int(reward.get("exp", 0))
    character, leveled = rpg_engine.add_character_exp(character, int(reward.get("exp", 0)))
    item = reward.get("item")
    if item:
        if not _append_inventory(character, item["id"]):
            reward["item_lost"] = True
    return character, leveled


def _peek_floor_types(state: dict[str, Any], ahead: int = 2) -> str:
    """占卜：揭示往后第 ahead 层的节点类型（跨章节自动顺延）。"""
    chapters = state["map"]["chapters"]
    chapter_index = int(state.get("chapter", 0))
    floor_index = int(state.get("floor", 0)) + ahead
    while chapter_index < len(chapters):
        floors = chapters[chapter_index]["floors"]
        if floor_index < len(floors):
            names = [
                "Boss" if choice["type"] == "boss" else rpg_renderer.NODE_NAMES.get(choice["type"], choice["type"])
                for choice in floors[floor_index]["choices"]
            ]
            return f"占卜显现前路（{chapters[chapter_index]['name']} 第 {floor_index + 1} 层）：" + "、".join(names)
        floor_index -= len(floors)
        chapter_index += 1
    return "占卜显现：前路尽头，已是终局。"


_SELL_EXCLUDED_TYPES = {"keepsake", "certificate"}


def _sellable_items(character: dict[str, Any]) -> list[dict[str, Any]]:
    """背包里可出售的道具（排除特殊道具/纪念物/证书、无价值物）。"""
    result: list[dict[str, Any]] = []
    for entry in character.get("inventory", []):
        try:
            template = rpg_engine.get_item_template(entry["id"])
        except ValueError:
            continue
        if (
            int(template.get("price", 0)) > 0
            and template.get("quality") != "special"
            and template.get("type") not in _SELL_EXCLUDED_TYPES
        ):
            result.append(entry)
    return result


def _render_sell_list(character: dict[str, Any], mult: float) -> str:
    items = _sellable_items(character)
    if not items:
        return "背包里没有可出售的道具。"
    lines = [f"出售道具（回收价 = 基础价 ×{mult:g}）｜金币：{character.get('gold', 0)}"]
    for index, entry in enumerate(items, 1):
        template = rpg_engine.get_item_template(entry["id"])
        price = max(1, round(int(template.get("price", 0)) * mult))
        lines.append(f"{index}. {template['name']} x{entry.get('quantity', 1)} → {price} 金")
    lines.append("发送 /<编号> 出售，/退出商店 结束。")
    return "\n".join(lines)


def _render_event_choices(evt: dict[str, Any]) -> str:
    lines = [f"【{evt['name']}】", evt["narration"], ""]
    for index, option in enumerate(evt["options"], 1):
        lines.append(f"{index}. {option['label']}")
    lines.append("发送 /<编号> 做出选择。")
    return "\n".join(lines)


def _build_social_battle(state: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    character = state["character"]
    level = rpg_engine.enemy_level_for_node(
        int(character["level"]),
        int(state.get("chapter", 0)) + 1,
        "battle",
    )
    return rpg_engine.generate_enemy(
        int(state.get("chapter", 0)) + 1,
        level,
        rng,
        rank="normal",
    )


def _state_prompt(state: dict[str, Any]) -> str:
    status = state["status"]
    if status == "standard_menu":
        return rpg_renderer.render_standard_menu()
    if status == "class_select":
        return rpg_renderer.render_class_choices()
    if status in {"stat_pending", "stat_assigned"} and state.get("character"):
        return rpg_renderer.render_character_card(state["character"])
    if status == "floor_select":
        return rpg_renderer.render_floor_choices(state["map"], int(state["chapter"]), int(state["floor"]))
    if status == "inventory":
        return rpg_renderer.render_inventory(state["character"], in_page=True)
    if status == "battle":
        return rpg_renderer.render_battle_state(state["character"], state["flags"]["enemy"])
    if status == "shop":
        return rpg_renderer.render_shop(state["flags"].get("shop_stock", []), int(state["character"].get("gold", 0)))
    if status == "npc":
        return "社交事件进行中。可用：/说服 /欺骗 /威吓"
    return "当前冒险正在进行。可用 /查看面板、/查看背包，或按当前提示继续。"


def _event_display_name(event: MessageEvent) -> str:
    sender = getattr(event, "sender", None)
    for key in ("card", "nickname"):
        if isinstance(sender, dict):
            value = sender.get(key)
        else:
            value = getattr(sender, key, None) if sender is not None else None
        if value:
            return str(value)
    return str(event.user_id)


async def _daily_player_welcome(event: MessageEvent, player: Any, player_name: str) -> tuple[dict[str, Any], str]:
    today = datetime.now().date().isoformat()
    player_data = dict(player)
    if player_data.get("gm_welcome_date") == today and player_data.get("gm_welcome_text"):
        return player_data, str(player_data["gm_welcome_text"])

    welcome = await rpg_ai.narrate_player_welcome(
        player_name,
        str(player_data["title"]),
        int(player_data["level"]),
        int(player_data["reputation"]),
    )
    if not welcome:
        welcome = "冒险者，今天要开始冒险了吗？"
    player_data = dict(set_rpg_player_gm_welcome(event.user_id, today, welcome))
    return player_data, welcome


rules_cmd = on_command("规则", priority=4, block=True)
adventure_cmd = on_command("冒险", aliases={"rpg"}, priority=4, block=True)
player_cmd = on_command("玩家", priority=4, block=True)
outside_bag_cmd = on_command("背包", priority=4, block=True)
achievement_book_cmd = on_command("成就书", aliases={"成就"}, priority=4, block=True)
standard_cmd = on_command("标准模式", priority=4, block=True)
creative_cmd = on_command("创意模式", priority=4, block=True)
mode_intro_cmd = on_command("模式简介", priority=4, block=True)
create_character_cmd = on_command("创建角色", priority=4, block=True)
choose_class_cmd = on_command("选择职业", priority=4, block=True)
random_character_cmd = on_command("随机创角", priority=4, block=True)
assign_stats_cmd = on_command("分配属性", priority=4, block=True)
reroll_stats_cmd = on_command("重新分配", priority=4, block=True)
start_adventure_cmd = on_command("开始冒险", priority=4, block=True)
panel_cmd = on_command("查看面板", priority=4, block=True)
inventory_cmd = on_command("查看背包", priority=4, block=True)
rebirth_cmd = on_command("转生", priority=4, block=True)
return_cmd = on_command("返回", priority=4, block=True)
yes_cmd = on_command("是", priority=4, block=True)
no_cmd = on_command("否", priority=4, block=True)
attack_cmd = on_command("攻击", priority=4, block=True)
skill_cmd = on_command("技能", priority=4, block=True)
item_cmd = on_command("道具", priority=4, block=True)
escape_cmd = on_command("逃跑", priority=4, block=True)
buy_cmd = on_command("购买", priority=4, block=True)
exit_shop_cmd = on_command("退出商店", priority=4, block=True)
equip_cmd = on_command("装备", priority=4, block=True)
unequip_cmd = on_command("卸下", priority=4, block=True)
forget_cmd = on_command("遗忘", priority=4, block=True)
social_cmds = {
    "说服": on_command("说服", priority=4, block=True),
    "欺骗": on_command("欺骗", priority=4, block=True),
    "威吓": on_command("威吓", priority=4, block=True),
}
number_cmds = {str(index): on_command(str(index), priority=4, block=True) for index in range(1, 10)}


@rules_cmd.handle()
async def handle_rules(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    await rules_cmd.finish(reply_message(event, rpg_renderer.render_rules()))


@adventure_cmd.handle()
async def handle_adventure(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None:
        await adventure_cmd.finish(reply_message(event, rpg_renderer.render_adventure_entry(False)))
    await adventure_cmd.finish(reply_message(event, _state_prompt(state)))


@player_cmd.handle()
async def handle_player(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    player = get_rpg_player(event.user_id)
    player_name = _event_display_name(event)
    player_data, welcome = await _daily_player_welcome(event, player, player_name)
    await player_cmd.finish(reply_message(
        event,
        rpg_renderer.render_outside_player_profile(
            player_data,
            player_name=player_name,
            next_exp=rpg_player_exp_to_next_level(int(player_data["level"])),
            gm_welcome=welcome,
        ),
    ))


@outside_bag_cmd.handle()
async def handle_outside_bag(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    items = list_rpg_player_items(event.user_id)
    await outside_bag_cmd.finish(reply_message(event, rpg_renderer.render_outside_inventory(items)))


@achievement_book_cmd.handle()
async def handle_achievement_book(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    get_rpg_player(event.user_id)
    unlocked = list_rpg_achievements(event.user_id)
    await achievement_book_cmd.finish(reply_message(
        event,
        rpg_renderer.render_achievement_book(unlocked, player_name=_event_display_name(event)),
    ))


@standard_cmd.handle()
async def handle_standard(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None:
        seed = f"{event.user_id}:{datetime.now().isoformat(timespec='seconds')}"
        run_id = create_rpg_run(
            event.user_id,
            "standard",
            status="standard_menu",
            seed=seed,
            flags={},
        )
        state = decode_rpg_run_state(get_active_rpg_run(event.user_id))
        state["id"] = run_id
    else:
        if state["status"] not in {"mode_select", "standard_menu"}:
            await standard_cmd.finish(reply_message(
                event,
                "当前冒险已经开始，不能重新进入标准模式。\n" + _state_prompt(state),
            ))
        state["status"] = "standard_menu"
        state = _save_state(state)
    await standard_cmd.finish(reply_message(event, rpg_renderer.render_standard_menu()))


@creative_cmd.handle()
async def handle_creative(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    await creative_cmd.finish(reply_message(event, rpg_renderer.render_creative_placeholder()))


@mode_intro_cmd.handle()
async def handle_mode_intro(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    await mode_intro_cmd.finish(reply_message(event, rpg_renderer.render_mode_intro()))


@create_character_cmd.handle()
async def handle_create_character(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None:
        await create_character_cmd.finish(reply_message(event, "请先发送 /冒险，然后选择 /标准模式。"))
    if state["status"] not in SETUP_STATUSES:
        await create_character_cmd.finish(reply_message(event, "冒险已经开始，无法重新创建角色。发送 /查看面板 继续。"))
    state["status"] = "class_select"
    _save_state(state)
    await create_character_cmd.finish(reply_message(event, rpg_renderer.render_class_choices()))


@choose_class_cmd.handle()
async def handle_choose_class(event: MessageEvent, args: Message = CommandArg()):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None:
        await choose_class_cmd.finish(reply_message(event, "请先发送 /冒险，然后选择 /标准模式。"))
    if state["status"] not in SETUP_STATUSES:
        await choose_class_cmd.finish(reply_message(event, "冒险已经开始，无法重新选择职业。"))
    class_id = _resolve_class_id(args.extract_plain_text())
    if class_id is None:
        await choose_class_cmd.finish(reply_message(event, "没有找到这个职业。请发送 /创建角色 查看职业池。"))
    state["flags"]["selected_class_id"] = class_id
    state["status"] = "stat_pending"
    _save_state(state)
    await choose_class_cmd.finish(reply_message(event, "职业已选择。发送 /分配属性 随机生成骰子属性。"))


@random_character_cmd.handle()
async def handle_random_character(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None:
        await random_character_cmd.finish(reply_message(event, "请先发送 /冒险，然后选择 /标准模式。"))
    if state["status"] not in SETUP_STATUSES:
        await random_character_cmd.finish(reply_message(event, "冒险已经开始，无法重新创建角色。"))
    rng = _rng_for_run(state, f"random-character:{datetime.now().timestamp()}")
    template = rng.choice(rpg_data.STANDARD_CLASSES)
    character = rpg_engine.create_standard_character(template["id"], rng)
    state["character"] = character
    state["flags"]["selected_class_id"] = template["id"]
    state["status"] = "stat_assigned"
    _save_state(state)
    text = (
        rpg_renderer.render_character_card(character)
        + "\n\n发送 /开始冒险 确认出发，或 /重新分配 重新随机。"
    )
    await random_character_cmd.finish(reply_message(event, text))


@assign_stats_cmd.handle()
async def handle_assign_stats(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None:
        await assign_stats_cmd.finish(reply_message(event, "请先选择职业。"))
    if state["status"] not in SETUP_STATUSES:
        await assign_stats_cmd.finish(reply_message(event, "冒险已经开始，无法重新分配属性。"))
    class_id = state["flags"].get("selected_class_id")
    if not class_id:
        await assign_stats_cmd.finish(reply_message(event, "请先发送 /选择职业 <职业>。"))
    rng = _rng_for_run(state, f"assign:{datetime.now().timestamp()}")
    character = rpg_engine.create_standard_character(str(class_id), rng)
    state["character"] = character
    state["status"] = "stat_assigned"
    _save_state(state)
    await assign_stats_cmd.finish(reply_message(event, rpg_renderer.render_random_stats(character)))


@reroll_stats_cmd.handle()
async def handle_reroll_stats(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None:
        await reroll_stats_cmd.finish(reply_message(event, "当前没有可重新分配的角色。"))
    if state["status"] not in SETUP_STATUSES:
        await reroll_stats_cmd.finish(reply_message(event, "冒险已经开始，无法重新分配属性。"))
    class_id = state["flags"].get("selected_class_id") or state.get("character", {}).get("class_id")
    if not class_id:
        await reroll_stats_cmd.finish(reply_message(event, "请先选择职业。"))
    rng = _rng_for_run(state, f"reroll:{datetime.now().timestamp()}")
    character = rpg_engine.create_standard_character(str(class_id), rng)
    state["character"] = character
    state["status"] = "stat_assigned"
    _save_state(state)
    await reroll_stats_cmd.finish(reply_message(event, rpg_renderer.render_random_stats(character)))


@start_adventure_cmd.handle()
async def handle_start_adventure(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None or not state.get("character"):
        await start_adventure_cmd.finish(reply_message(event, "请先创建角色并分配属性。"))
    if state["status"] != "stat_assigned":
        await start_adventure_cmd.finish(reply_message(event, "冒险已经开始，无法重复出发。发送 /查看面板 继续。"))
    rng = _rng_for_run(state, "map")
    character = state["character"]
    character = _sync_special_passives(character, event.user_id)
    character["background"] = await rpg_ai.narrate_opening(character) or _fallback_background(character)
    state["character"] = character
    player = get_rpg_player(event.user_id)
    state["flags"]["start_reputation"] = int(player["reputation"])
    state["flags"]["start_reputation_title"] = str(player["title"])
    # 记录开局幸运值（用于隐藏成就 #5），并初始化本局成就计数器
    state["flags"]["start_luck"] = int(character.get("random_stats", {}).get("luck", 0))
    state["flags"]["ach"] = rpg_achievements.new_run_counters()
    state["map"] = rpg_engine.generate_run_map(rng, int(player["reputation"]))
    state["chapter"] = 0
    state["floor"] = 0
    state["status"] = "floor_select"
    _save_state(state)
    text = (
        rpg_renderer.render_background_ready(character)
        + "\n\n"
        + rpg_renderer.render_floor_choices(state["map"], 0, 0)
    )
    await start_adventure_cmd.finish(reply_message(event, text))


@panel_cmd.handle()
async def handle_panel(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None or not state.get("character"):
        await panel_cmd.finish(reply_message(event, "当前没有冒险角色。"))
    await panel_cmd.finish(reply_message(event, rpg_renderer.render_character_card(state["character"])))


@inventory_cmd.handle()
async def handle_inventory(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None or not state.get("character"):
        await inventory_cmd.finish(reply_message(event, "当前没有冒险背包。"))
    # 仅在层间探索（floor_select）这一局外枢纽进入背包二级页，可 /<编号> 使用消耗品、/返回 回到当前层。
    # 其它状态（战斗 / 商店 / 事件 / 出售 / 确认等）只读查看，避免打断当前交互。
    if state["status"] in {"floor_select", "inventory"}:
        if state["status"] != "inventory":
            state["flags"]["inventory_return"] = state["status"]
            state["status"] = "inventory"
            _save_state(state)
        await inventory_cmd.finish(reply_message(event, rpg_renderer.render_inventory(state["character"], in_page=True)))
    await inventory_cmd.finish(reply_message(event, rpg_renderer.render_inventory(state["character"])))


@equip_cmd.handle()
async def handle_equip(event: MessageEvent, args: Message = CommandArg()):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None or not state.get("character"):
        await equip_cmd.finish(reply_message(event, "当前没有冒险角色。"))
    if state["status"] in BATTLE_STATUSES or state["status"] == "confirm":
        await equip_cmd.finish(reply_message(event, "战斗中无法更换装备。"))
    text = args.extract_plain_text().strip()
    if not text.isdigit():
        await equip_cmd.finish(reply_message(event, "用法：/装备 <背包编号>。先 /查看背包 查看编号。"))
    character = state["character"]
    ok, reason, item = rpg_engine.equip_item(character, int(text) - 1)
    if not ok:
        msg = {
            "no_item": "没有这个背包编号。",
            "not_equipment": f"{item['name'] if item else '该道具'} 不是可穿戴的装备。",
            "slots_full": f"装备栏已满（上限 {rpg_data.MAX_EQUIPPED} 件），请先 /卸下 <编号>。",
        }.get(reason, "无法装备该道具。")
        await equip_cmd.finish(reply_message(event, msg))
    state["character"] = character
    _save_state(state)
    in_page = state["status"] == "inventory"
    await equip_cmd.finish(reply_message(event, f"已装备 {item['name']}。\n" + rpg_renderer.render_inventory(character, in_page=in_page)))


@unequip_cmd.handle()
async def handle_unequip(event: MessageEvent, args: Message = CommandArg()):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None or not state.get("character"):
        await unequip_cmd.finish(reply_message(event, "当前没有冒险角色。"))
    if state["status"] in BATTLE_STATUSES or state["status"] == "confirm":
        await unequip_cmd.finish(reply_message(event, "战斗中无法更换装备。"))
    text = args.extract_plain_text().strip()
    if not text.isdigit():
        await unequip_cmd.finish(reply_message(event, "用法：/卸下 <装备编号>。先 /查看背包 查看装备栏编号。"))
    character = state["character"]
    ok, reason, item = rpg_engine.unequip_item(character, int(text) - 1)
    if not ok:
        msg = {
            "no_item": "没有这个装备编号。",
            "backpack_full": (
                f"背包已满（上限 {rpg_engine.inventory_backpack_slots(character)} 格），无法卸下。"
            ),
        }.get(reason, "无法卸下该装备。")
        await unequip_cmd.finish(reply_message(event, msg))
    state["character"] = character
    _save_state(state)
    in_page = state["status"] == "inventory"
    await unequip_cmd.finish(reply_message(event, f"已卸下 {item['name']}。\n" + rpg_renderer.render_inventory(character, in_page=in_page)))


@forget_cmd.handle()
async def handle_forget(event: MessageEvent, args: Message = CommandArg()):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None or not state.get("character"):
        await forget_cmd.finish(reply_message(event, "当前没有冒险角色。"))
    if state["status"] in BATTLE_STATUSES or state["status"] == "confirm":
        await forget_cmd.finish(reply_message(event, "战斗中无法遗忘技能。"))
    character = state["character"]
    text = args.extract_plain_text().strip()
    if not text.isdigit():
        await forget_cmd.finish(reply_message(
            event, "用法：/遗忘 <技能编号>（不返还）。\n" + rpg_renderer.render_skills(character)
        ))
    ok, reason, name = rpg_engine.forget_skill(character, int(text) - 1)
    if not ok:
        msg = {
            "no_skill": "没有这个技能编号。",
            "last_skill": "至少要保留 1 个技能，无法再遗忘。",
            "innate": f"出生技【{name}】不能遗忘。",
        }.get(reason, "无法遗忘该技能。")
        await forget_cmd.finish(reply_message(event, msg + "\n" + rpg_renderer.render_skills(character)))
    state["character"] = character
    _save_state(state)
    await forget_cmd.finish(reply_message(event, f"已遗忘【{name}】。\n" + rpg_renderer.render_skills(character)))


@rebirth_cmd.handle()
async def handle_rebirth(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None:
        await rebirth_cmd.finish(reply_message(event, "当前没有正在进行的冒险。"))
    state["flags"]["confirm_action"] = {"type": "rebirth", "restore": state["status"]}
    state["status"] = "confirm"
    _save_state(state)
    await rebirth_cmd.finish(reply_message(event, rpg_renderer.render_confirm("转生并结束本局冒险")))


@return_cmd.handle()
async def handle_return(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None:
        await return_cmd.finish(reply_message(event, "当前没有可返回的冒险菜单。"))
    # 背包二级页：直接收起回到进入前的状态，无需二次确认
    if state["status"] == "inventory":
        state["status"] = state["flags"].pop("inventory_return", "floor_select")
        _save_state(state)
        await return_cmd.finish(reply_message(event, "你收起了背包。\n" + _state_prompt(state)))
    target = RETURN_TARGETS.get(state["status"])
    if target is None:
        await return_cmd.finish(reply_message(event, "当前状态不能返回上一级。"))
    state["flags"]["confirm_action"] = {"type": "return", "target": target, "restore": state["status"]}
    state["status"] = "confirm"
    _save_state(state)
    await return_cmd.finish(reply_message(event, rpg_renderer.render_confirm("返回上一级")))


@no_cmd.handle()
async def handle_no(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None:
        await no_cmd.finish(reply_message(event, "没有需要取消的确认。"))
    action = state["flags"].pop("confirm_action", None)
    if not action:
        await no_cmd.finish(reply_message(event, "没有需要取消的确认。"))
    state["status"] = action.get("restore", state["status"])
    _save_state(state)
    await no_cmd.finish(reply_message(event, "已取消。\n" + _state_prompt(state)))


@yes_cmd.handle()
async def handle_yes(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None:
        await yes_cmd.finish(reply_message(event, "没有需要确认的操作。"))
    action = state["flags"].pop("confirm_action", None)
    if not action:
        await yes_cmd.finish(reply_message(event, "没有需要确认的操作。"))
    if action["type"] == "return":
        state["status"] = action["target"]
        _save_state(state)
        await yes_cmd.finish(reply_message(event, _state_prompt(state)))
    if action["type"] == "rebirth":
        ending = await rpg_ai.narrate_ending(state["character"], "rebirth")
        text = _finish_run(state, "rebirth")
        if ending:
            text = ending + "\n\n" + text
        await yes_cmd.finish(reply_message(event, text))
    if action["type"] == "escape":
        rng = _rng_for_run(state, f"escape:{datetime.now().timestamp()}")
        result = rpg_engine.roll_escape(state["character"], state["flags"]["enemy"], rng)
        if result["success"]:
            state["flags"].pop("enemy", None)
            state["flags"].pop("bounty_reward", None)  # 逃离赏金战不结算奖励，清掉以免漏给下一场
            _clear_combat_statuses(state["character"])  # 逃脱后清掉战斗中的临时状态
            text = f"逃跑成功，成功率 {result['rate']:.1f}%。\n" + _render_current_floor_or_finish(state)
            await yes_cmd.finish(reply_message(event, text))
        state["status"] = "battle"
        _save_state(state)
        await yes_cmd.finish(reply_message(event, f"逃跑失败，成功率 {result['rate']:.1f}%。\n" + _state_prompt(state)))
    await yes_cmd.finish(reply_message(event, "这个确认动作暂未实现。"))


def _clear_combat_statuses(character: dict[str, Any]) -> dict[str, Any]:
    """战斗结束时清空临时状态（增益/燃烧等），并重算面板使被 buff 改过的属性归位。"""
    if character.get("statuses"):
        character["statuses"] = []
        rpg_engine.recompute_character_stats(character)
    return character


def _execute_action(
    actor: dict[str, Any],
    opponent: dict[str, Any],
    action: dict[str, Any],
    actor_name: str,
    opponent_name: str,
    rng: random.Random,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """让 actor 对 opponent 执行一个动作（普攻 / 技能），返回更新后的双方与叙述行。

    技能伤害命中后按概率附加异常状态；支援技自愈。玩家与敌方共用这一段逻辑。
    """
    lines: list[str] = []
    if action["type"] == "item":
        item = action["item"]
        actor, eff_lines = rpg_engine.apply_consumable_effects(actor, item, rng)
        lines.append(f"{actor_name}使用了 {item['name']}。")
        lines.extend(eff_lines)
        return actor, opponent, lines
    if action["type"] == "skill":
        skill = rpg_engine.get_skill_template(action["skill_id"])
        result = rpg_engine.resolve_skill_attack(actor, opponent, action["skill_id"], rng)
        if not result.get("ok"):  # MP 不足等异常，退化为普攻
            result = rpg_engine.resolve_basic_attack(actor, opponent, rng)
            opponent = result["defender"]
            lines.append(rpg_renderer.render_attack_result(actor_name, opponent_name, result))
            return actor, opponent, lines
        actor = result["attacker"]
        lines.append(f"{actor_name}使用了 {skill['name']}。")
        if result.get("support_only"):
            heal = int(result.get("heal", 0))
            if heal > 0:
                lines.append(f"{actor_name}恢复 HP {heal}。")
            buff = result.get("buff")
            if buff:
                mod_text = "、".join(
                    f"{k}{'+' if int(v) >= 0 else ''}{int(v)}" for k, v in dict(buff.get("mods", {})).items()
                )
                lines.append(
                    f"{actor_name}获得增益【{buff.get('name', '增益')}】：{mod_text}，持续 {int(buff.get('duration', 3))} 回合。"
                )
        else:
            opponent = result["defender"]
            hits = int(result.get("hits", 1))
            line = rpg_renderer.render_attack_result(actor_name, opponent_name, result)
            if hits > 1 and not result.get("dodged"):
                line = line.replace("造成", f"连击 {hits} 段，共造成")
            lines.append(line)
            self_buff = skill.get("self_buff")
            if self_buff:
                mod_text = "、".join(
                    f"{k}{int(v):+d}" for k, v in dict(self_buff.get("mods", {})).items()
                )
                lines.append(
                    f"{actor_name}获得【{self_buff.get('name', '增益')}】：{mod_text}，持续 {int(self_buff.get('duration', 2))} 回合。"
                )
            enemy_debuff = skill.get("enemy_debuff")
            if enemy_debuff and not result.get("dodged"):
                mod_text = "、".join(
                    f"{k}{int(v):+d}" for k, v in dict(enemy_debuff.get("mods", {})).items()
                )
                lines.append(
                    f"{opponent_name}被施加【{enemy_debuff.get('name', '削弱')}】：{mod_text}，持续 {int(enemy_debuff.get('duration', 3))} 回合。"
                )
            if not result.get("dodged"):
                opponent, status_line = rpg_engine.apply_skill_status(skill, opponent, rng)
                if status_line:
                    lines.append(status_line)
    else:
        result = rpg_engine.resolve_basic_attack(actor, opponent, rng)
        opponent = result["defender"]
        lines.append(rpg_renderer.render_attack_result(actor_name, opponent_name, result))
    return actor, opponent, lines


def _is_offensive(turn_action: dict[str, Any]) -> bool:
    """该动作是否为攻击性动作（普攻或非支援技），决定能否触发连击。"""
    if turn_action["type"] == "attack":
        return True
    if turn_action["type"] == "skill":
        return rpg_engine.get_skill_template(turn_action["skill_id"]).get("type") != "support"
    return False


def _battle_round(
    state: dict[str, Any],
    action: dict[str, Any],
    rng: random.Random,
) -> dict[str, Any]:
    """按 SPD 决定出手顺序跑一个回合：回合开始结算状态，再行动，含技能附加状态。

    出手顺序：SPD 高者先手，相同则玩家先手（《数值设定》）。敌方按 AI 选择普攻或技能。
    返回 {"outcome": invalid|enemy_defeated|player_defeated|continue, "lines": [...]}，
    并就地更新 state["character"] 与 state["flags"]["enemy"]。
    """
    character = state["character"]
    enemy = state["flags"]["enemy"]
    lines: list[str] = []

    # 战斗开始：施加事件里预约的“下一场战斗”增益（战斗外不动属性，避免被 recompute 抹掉而漂移）
    pending = character.get("pending_buffs")
    if pending:
        for buff in pending:
            character = rpg_engine.apply_buff(
                character,
                name=str(buff.get("name", "增益")),
                mods=dict(buff.get("mods", {})),
                duration=int(buff.get("duration", 1)),
            )
            lines.append(f"【{buff.get('name', '增益')}】生效。")
        character["pending_buffs"] = []
        state["character"] = character

    if action["type"] == "skill":
        skill = rpg_engine.get_skill_template(action["skill_id"])
        cur_mp = int(character.get("current_mp", character["stats"].get("mp", 0)))
        if cur_mp < int(skill.get("mp_cost", 0)):
            return {"outcome": "invalid", "lines": ["MP 不足，无法使用该技能。"]}

    player_first = rpg_engine.effective_spd(character) >= rpg_engine.effective_spd(enemy)
    order = ["player", "enemy"] if player_first else ["enemy", "player"]
    units = {"player": character, "enemy": enemy}
    display = {"player": "你", "enemy": enemy["name"]}
    outcome = "continue"
    item_used = False

    for index, side in enumerate(order):
        opp_side = "enemy" if side == "player" else "player"
        actor = units[side]
        # 回合开始：结算自身状态（伤害/麻痹），递减持续回合
        actor, tick_lines, skipped = rpg_engine.tick_statuses(actor, units[opp_side], rng)
        units[side] = actor
        for tick_line in tick_lines:
            lines.append(f"{display[side]}：{tick_line}")
        if int(actor["current_hp"]) <= 0:
            outcome = "enemy_defeated" if side == "enemy" else "player_defeated"
            break
        if skipped:
            continue

        # 打断：后手方若被先手方（SPD ≥ 其 1.5 倍）抢攻，则失去本回合行动
        if index == 1:
            rate = rpg_engine.interrupt_rate(units[order[0]], actor)
            if rate > 0 and rng.random() * 100 < rate:
                lines.append(f"{display[order[0]]}抢攻打断了{display[side]}的行动！")
                continue

        turn_action = action if side == "player" else rpg_engine.choose_enemy_action(units[side], rng)
        opponent_hp_before = int(units[opp_side].get("current_hp", 0))
        actor_after, opponent_after, act_lines = _execute_action(
            units[side], units[opp_side], turn_action, display[side], display[opp_side], rng
        )
        if opp_side == "player" and _has_item(opponent_after, "fragile_shield") and not state["flags"].get("fragile_shield_used"):
            damage_taken = opponent_hp_before - int(opponent_after.get("current_hp", opponent_hp_before))
            if 0 < damage_taken <= 40:
                max_hp = int(opponent_after.get("stats", {}).get("hp", opponent_hp_before))
                opponent_after["current_hp"] = min(max_hp, int(opponent_after.get("current_hp", 0)) + damage_taken)
                _consume_item_by_id(opponent_after, "fragile_shield")
                state["flags"]["fragile_shield_used"] = True
                act_lines.append(f"脆弱的护盾触发：抵挡了 {damage_taken} 点伤害。")
        units[side] = actor_after
        units[opp_side] = opponent_after
        lines.extend(act_lines)
        if side == "player" and turn_action["type"] == "item":
            item_used = True  # 道具真正在玩家回合被使用了（未被麻痹跳过），handler 据此扣除
        if int(units[opp_side]["current_hp"]) <= 0:
            outcome = "enemy_defeated" if opp_side == "enemy" else "player_defeated"
            break

        # 连击：攻击性动作后按 combo_rate(spd+luck) 追加普攻，最多 MAX_COMBO_HITS 次
        if _is_offensive(turn_action):
            for _ in range(rpg_data.MAX_COMBO_HITS):
                if int(units[opp_side]["current_hp"]) <= 0:
                    break
                if rng.random() * 100 >= rpg_engine.combo_rate(units[side]):
                    break
                follow = rpg_engine.resolve_basic_attack(units[side], units[opp_side], rng)
                units[opp_side] = follow["defender"]
                lines.append("（连击）" + rpg_renderer.render_attack_result(display[side], display[opp_side], follow))
            if int(units[opp_side]["current_hp"]) <= 0:
                outcome = "enemy_defeated" if opp_side == "enemy" else "player_defeated"
                break

    state["character"] = units["player"]
    state["flags"]["enemy"] = units["enemy"]
    if outcome == "player_defeated":
        revive_line = _try_special_revive(state)
        if revive_line:
            lines.append(revive_line)
            outcome = "continue"
    return {"outcome": outcome, "lines": lines, "item_used": item_used}


async def _send_encounter(event, matcher, state: dict[str, Any], prefix_lines: list[str] | None = None):
    """战斗登场：生成 AI 遭遇旁白，拼上战斗面板后发送。AI 失败则只发面板，不影响游戏。"""
    # 战斗次数 +1（含普通/精英/Boss/社交触发战/赏金战，均收口于此）。计数器随存档持久化。
    _ach_counters(state)["battles"] = int(_ach_counters(state).get("battles", 0)) + 1
    _save_state(state)
    character = state["character"]
    enemy = state["flags"]["enemy"]
    parts = list(prefix_lines or [])
    intro = await rpg_ai.narrate_encounter(character, enemy)
    if intro:
        parts.append(intro)
    parts.append(rpg_renderer.render_battle_state(character, enemy))
    await matcher.finish(reply_message(event, "\n".join(parts)))


async def _finish_battle_round(event, matcher, state: dict[str, Any], rng: random.Random, result: dict[str, Any]):
    """根据 _battle_round 的结果完成发奖 / 死亡结算 / 继续战斗的收尾与发送。"""
    lines = result["lines"]
    outcome = result["outcome"]

    if outcome == "invalid":
        state["status"] = "battle"
        _save_state(state)
        await matcher.finish(reply_message(event, "\n".join(lines) + "\n" + _state_prompt(state)))

    if outcome == "enemy_defeated":
        enemy = state["flags"]["enemy"]
        character = _clear_combat_statuses(state["character"])  # 战斗结束清掉临时增益/持续状态
        reward = rpg_engine.boss_reward(enemy["id"], rng) if enemy.get("rank") == "boss" else rpg_engine.enemy_reward(enemy["rank"], rng)
        # E5：技能书投放——Boss 必出高品质职业书；普通敌人约 20% 把掉落替换为职业书
        if enemy.get("rank") == "boss":
            book = rpg_engine.roll_skill_book(character.get("class_id"), rng, qualities=["uncommon", "legendary"])
            if book:
                reward["item"] = book
        elif reward.get("item") and rng.randint(1, 100) <= 20:
            book = rpg_engine.roll_skill_book(character.get("class_id"), rng)
            if book:
                reward["item"] = book
        if _has_item(character, "rogue_gloves") and int(reward.get("gold", 0)) > 0:
            bonus_gold = max(1, int(reward.get("gold", 0)) * 25 // 100)
            reward["gold"] = int(reward.get("gold", 0)) + bonus_gold
            lines.append(f"盗贼手套触发：额外获得 {bonus_gold} 金币。")
        if state["flags"].pop("soul_gem_active", None):
            enemy_skills = [sid for sid in enemy.get("skills", []) if sid not in character.get("skills", [])]
            if enemy_skills:
                learned = rng.choice(enemy_skills)
                ok, reason = rpg_engine.learn_skill(character, learned)
                if ok:
                    try:
                        skill_name = rpg_engine.get_skill_template(learned)["name"]
                    except ValueError:
                        skill_name = learned
                    lines.append(f"灵魂宝石触发：学会了【{skill_name}】。")
        character, leveled = _grant_reward(character, reward)
        carry_out = reward.get("carry_out", [])
        if carry_out:
            state["flags"].setdefault("carry_out_items", []).extend(carry_out)
        lines.append(rpg_renderer.render_reward(reward))
        if leveled:
            lines.append(f"你提升了 {leveled} 级。")
        bounty = state["flags"].pop("bounty_reward", None)  # 赏金任务：胜利后额外结算
        if bounty:
            character, bounty_lines = rpg_engine.resolve_event_effects(
                character, bounty, chapter=int(state.get("chapter", 0)), rng=rng
            )
            lines.append("赏金任务完成！")
            lines.extend(bounty_lines)
        state["character"] = character
        state["flags"].pop("enemy", None)
        floor_text = _render_current_floor_or_finish(state)
        if state.pop("_run_finished", None) == "victory":  # 击败最终 Boss，通关结局
            ending = await rpg_ai.narrate_ending(state["character"], "victory")
            if ending:
                floor_text = ending + "\n\n" + floor_text
        lines.append(floor_text)
        await matcher.finish(reply_message(event, "\n".join(lines)))

    if outcome == "player_defeated":
        _save_state(state)
        death_text = _finish_run(state, "death")
        state.pop("_run_finished", None)
        ending = await rpg_ai.narrate_ending(state["character"], "death")
        body = "\n".join(lines)
        if ending:
            body += "\n\n" + ending
        await matcher.finish(reply_message(event, body + "\n" + death_text))

    state["status"] = "battle"
    _save_state(state)
    lines.append(rpg_renderer.render_battle_state(state["character"], state["flags"]["enemy"]))
    await matcher.finish(reply_message(event, "\n".join(lines)))


@attack_cmd.handle()
async def handle_attack(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None or state["status"] != "battle":
        await attack_cmd.finish(reply_message(event, "当前不在战斗中。"))
    rng = _rng_for_run(state, f"attack:{datetime.now().timestamp()}")
    result = _battle_round(state, {"type": "attack"}, rng)
    await _finish_battle_round(event, attack_cmd, state, rng, result)


@skill_cmd.handle()
async def handle_skill(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None or state["status"] != "battle":
        await skill_cmd.finish(reply_message(event, "当前不在战斗中。"))
    state["status"] = "skill_select"
    _save_state(state)
    await skill_cmd.finish(reply_message(event, rpg_renderer.render_skill_list(state["character"])))


@item_cmd.handle()
async def handle_item(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None or state["status"] != "battle":
        await item_cmd.finish(reply_message(event, "当前不在战斗中。"))
    state["status"] = "item_select"
    _save_state(state)
    await item_cmd.finish(reply_message(event, rpg_renderer.render_item_list(state["character"])))


@escape_cmd.handle()
async def handle_escape(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None or state["status"] != "battle":
        await escape_cmd.finish(reply_message(event, "当前不在战斗中。"))
    if state["flags"].get("enemy", {}).get("rank") == "boss":
        await escape_cmd.finish(reply_message(event, "Boss 战无法逃跑。"))
    state["flags"]["confirm_action"] = {"type": "escape", "restore": "battle"}
    state["status"] = "confirm"
    _save_state(state)
    await escape_cmd.finish(reply_message(event, rpg_renderer.render_confirm("逃跑")))


@buy_cmd.handle()
async def handle_buy(event: MessageEvent, args: Message = CommandArg()):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None or state["status"] != "shop":
        await buy_cmd.finish(reply_message(event, "当前不在商店中。"))
    text = args.extract_plain_text().strip()
    if not text.isdigit():
        await buy_cmd.finish(reply_message(event, "用法：/购买 <编号>"))
    index = int(text) - 1
    stock = state["flags"].get("shop_stock", [])
    if index < 0 or index >= len(stock):
        await buy_cmd.finish(reply_message(event, "没有这个商品编号。"))
    item = stock[index]
    price = int(item["final_price"])
    character = state["character"]
    if int(character.get("gold", 0)) < price:
        await buy_cmd.finish(reply_message(event, "金币不足。"))
    if item.get("blind"):  # 盲盒：买下才随机出该稀有度的具体道具
        rng = _rng_for_run(state, f"blind:{index}:{datetime.now().timestamp()}")
        rolled = rpg_engine.roll_blind_item(item["quality"], rng)
        if rolled is None:
            await buy_cmd.finish(reply_message(event, "这个货位空了。"))
        can_buy, reason = rpg_engine.can_add_item(character, rolled["id"])
        if not can_buy:
            await buy_cmd.finish(reply_message(event, f"无法购买：{ADD_ITEM_FAIL_REASONS.get(reason, '背包放不下')}。"))
        character["gold"] = int(character.get("gold", 0)) - price
        rpg_engine.add_item_to_inventory(character, rolled["id"])
        _sync_special_passives(character)
        stock.pop(index)  # 盲盒一次性，买走后该货位消失
        state["character"] = character
        _save_state(state)
        await buy_cmd.finish(reply_message(event, f"开出了：{rolled['name']}！\n" + rpg_renderer.render_shop(stock, character["gold"])))
    can_buy, reason = rpg_engine.can_add_item(character, item["id"])
    if not can_buy:
        await buy_cmd.finish(reply_message(event, f"无法购买：{ADD_ITEM_FAIL_REASONS.get(reason, '背包放不下')}。"))
    character["gold"] = int(character.get("gold", 0)) - price
    rpg_engine.add_item_to_inventory(character, item["id"])
    _sync_special_passives(character)
    state["character"] = character
    _save_state(state)
    await buy_cmd.finish(reply_message(event, f"购买成功：{item['name']}。\n" + rpg_renderer.render_shop(stock, character["gold"])))


@exit_shop_cmd.handle()
async def handle_exit_shop(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None or state["status"] not in {"shop", "npc_sell"}:
        await exit_shop_cmd.finish(reply_message(event, "当前不在商店中。"))
    state["flags"].pop("shop_stock", None)
    state["flags"].pop("sell_mult", None)
    state["flags"].pop("shop_discounted", None)
    state["flags"].pop("shop_social_used", None)
    await exit_shop_cmd.finish(reply_message(event, "你离开了商店。\n" + _render_current_floor_or_finish(state)))


async def _handle_social(event: MessageEvent, matcher_name: str):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None or state["status"] not in {"npc", "shop"}:
        await social_cmds[matcher_name].finish(reply_message(event, "当前没有可社交的事件。"))

    is_shop = state["status"] == "shop"
    # 每家店的社交机会只有一次：判定过（无论成败）就不能再社交，避免反复 /说服 刷判定。
    if is_shop and state["flags"].get("shop_social_used"):
        await social_cmds[matcher_name].finish(reply_message(
            event,
            "你已经和这家店的老板交涉过了，他不会再理会第二次。\n"
            + rpg_renderer.render_shop(state["flags"].get("shop_stock", []), int(state["character"].get("gold", 0))),
        ))
    rng = _rng_for_run(state, f"social:{matcher_name}:{datetime.now().timestamp()}")
    character = state["character"]
    affinity = int(state["flags"].get("npc_affinity", 0))
    result = rpg_engine.resolve_social_action(matcher_name, character, affinity, rng)
    _record_social_attempt(state, matcher_name, bool(result["success"]))
    lines = [
        f"{matcher_name} 判定：d20={result['roll']}，成功率 {result['rate']:.1f}%。",
        "判定成功。" if result["success"] else "判定失败。",
    ]
    if result.get("charm_delta"):
        # 魅力变化写进 base_random_stats（持久层），再重算面板，
        # 避免之后 /装备 /卸下 触发的重算把这次变化覆盖掉。
        character.setdefault("base_random_stats", dict(character.get("random_stats", {})))
        character["base_random_stats"]["charm"] = max(
            -20,
            int(character["base_random_stats"].get("charm", 0)) + int(result["charm_delta"]),
        )
        rpg_engine.recompute_character_stats(character)
        state["character"] = character
        lines.append(f"魅力变化：{result['charm_delta']}。")

    # —— 商店社交：成功 → 全场折扣（每家店仅一次）并留在商品页；「说服」失败也留在商品页（无折扣）；
    #    「欺骗/威吓」失败被赶出商店（不打架）——
    if is_shop:
        state["flags"]["shop_social_used"] = True  # 标记本店社交机会已用掉
        stock = state["flags"].get("shop_stock", [])
        if result["success"]:
            if state["flags"].get("shop_discounted"):
                lines.append("老板已经给过你折扣了，价格压不下去了。")
            else:
                discount = rng.randint(10, 30)  # 随机 10%~30%
                for item in stock:
                    item["final_price"] = max(1, round(int(item["final_price"]) * (100 - discount) / 100))
                state["flags"]["shop_discounted"] = True
                lines.append(f"社交成功！老板松口打了折，全场 -{discount}%。")
            state["character"] = character
            _save_state(state)
            lines.append("你仍可以继续选购。")
            lines.append(rpg_renderer.render_shop(stock, int(character.get("gold", 0))))
            await social_cmds[matcher_name].finish(reply_message(event, "\n".join(lines)))
        if matcher_name == "说服":  # 说服失败：脸皮厚，留在商店但没折扣
            state["character"] = character
            _save_state(state)
            lines.append("老板不为所动，价格照旧。")
            lines.append(rpg_renderer.render_shop(stock, int(character.get("gold", 0))))
            await social_cmds[matcher_name].finish(reply_message(event, "\n".join(lines)))
        state["flags"].pop("shop_stock", None)
        state["flags"].pop("shop_discounted", None)
        state["character"] = character
        lines.append("你被赶出了商店。")
        lines.append(_render_current_floor_or_finish(state))
        await social_cmds[matcher_name].finish(reply_message(event, "\n".join(lines)))

    # —— NPC 社交：保持原有「欺骗/威吓」失败可能引发战斗的逻辑 ——
    state["flags"].pop("npc_affinity", None)
    if result.get("battle"):
        enemy = _build_social_battle(state, rng)
        state["flags"]["enemy"] = enemy
        state["status"] = "battle"
        _save_state(state)
        lines.append("社交失败引发了战斗。")
        await _send_encounter(event, social_cmds[matcher_name], state, lines)

    _save_state(state)
    lines.append(_render_current_floor_or_finish(state))
    await social_cmds[matcher_name].finish(reply_message(event, "\n".join(lines)))


for _name, _matcher in social_cmds.items():

    @_matcher.handle()
    async def _handle(event: MessageEvent, name: str = _name):
        await _handle_social(event, name)


async def _handle_number(event: MessageEvent, number: int):
    if should_ignore_group_message(event):
        return
    state = _load_state(event.user_id)
    if state is None:
        await number_cmds[str(number)].finish(reply_message(event, "当前没有可选择的冒险选项。"))

    if state["status"] == "floor_select":
        choices = _current_floor_choices(state)
        choice = next((item for item in choices if int(item["index"]) == number), None)
        if choice is None:
            await number_cmds[str(number)].finish(reply_message(event, "没有这个选项编号。"))
        rng = _rng_for_run(state, f"node:{state['chapter']}:{state['floor']}:{number}")
        node_type = choice["type"]
        character = state["character"]
        if node_type in {"battle", "elite"}:
            level = rpg_engine.enemy_level_for_node(character["level"], int(state["chapter"]) + 1, node_type)
            enemy = rpg_engine.generate_enemy(
                int(state["chapter"]) + 1,
                level,
                rng,
                elite=node_type == "elite",
            )
            state["flags"]["enemy"] = enemy
            state["status"] = "battle"
            _save_state(state)
            await _send_encounter(event, number_cmds[str(number)], state)
        if node_type == "boss":
            enemy = rpg_engine.generate_boss(choice["boss_id"], rng)
            state["flags"]["enemy"] = enemy
            state["status"] = "battle"
            _save_state(state)
            await _send_encounter(event, number_cmds[str(number)], state)
        if node_type == "rest":
            state["character"] = rpg_engine.apply_rest(character)
            _save_state(state)
            await number_cmds[str(number)].finish(reply_message(event, "你在休息点恢复了 HP 与 MP。\n" + _render_current_floor_or_finish(state)))
        if node_type == "shop":
            random_stats = character["random_stats"]
            stock = rpg_engine.generate_shop_stock(
                random_stats["luck"], random_stats["charm"], rng,
                discount=int(character.get("shop_discount", 0)) + _special_shop_discount(character),
            )
            if _has_item(character, "treasure_map_fragment"):
                extra = rpg_engine.generate_shop_stock(
                    random_stats["luck"], random_stats["charm"], rng,
                    count=1,
                    discount=int(character.get("shop_discount", 0)) + _special_shop_discount(character),
                )
                stock.extend(extra)
                _consume_item_by_id(character, "treasure_map_fragment")
            # E5：约 35% 概率上架一本职业技能书（普通~稀有品质池）
            if rng.randint(1, 100) <= 35:
                book = rpg_engine.roll_skill_book(
                    character.get("class_id"), rng, qualities=["common", "practical", "rare"]
                )
                if book:
                    book = dict(book)
                    book["quality_score"] = 0
                    book["final_price"] = max(1, int(book.get("price", 0)))
                    stock.append(book)
            state["flags"]["shop_stock"] = stock
            state["flags"].pop("shop_discounted", None)  # 新店重置社交折扣资格
            state["flags"].pop("shop_social_used", None)  # 新店重置社交机会
            state["status"] = "shop"
            _save_state(state)
            await number_cmds[str(number)].finish(reply_message(event, rpg_renderer.render_shop(stock, character.get("gold", 0))))
        if node_type == "mystery":
            reputation = int(state.get("flags", {}).get("start_reputation", 0))
            outcome = rpg_engine.random_event_outcome(character["random_stats"]["luck"], rng, reputation)
            pool_name = outcome  # positive / negative / neutral
            if (
                outcome == "positive"
                and rng.randint(1, 100) <= rpg_data.SPECIAL_EVENT_CHANCE
                and rpg_data.EVENT_POOLS.get("special")
            ):
                pool_name = "special"
            triggered = state["flags"].setdefault("triggered_events", [])
            pool = [
                evt for evt in rpg_data.EVENT_POOLS.get(pool_name, [])
                if not (evt.get("once") and evt["id"] in triggered)
            ]
            if pool:
                evt = rng.choice(pool)
                if evt.get("once"):
                    triggered.append(evt["id"])
                if evt.get("options"):  # 抉择型事件 → 进入选项流程
                    state["flags"]["pending_event"] = evt
                    state["status"] = "event_choice"
                    _save_state(state)
                    await number_cmds[str(number)].finish(reply_message(event, _render_event_choices(evt)))
                character, eff_lines = rpg_engine.resolve_event_effects(
                    character, evt["effects"], chapter=int(state.get("chapter", 0)), rng=rng
                )
                state["character"] = character
                text = f"【{evt['name']}】\n{evt['narration']}\n" + "\n".join(eff_lines)
            else:
                text = "神秘事件平静地过去了，什么也没有发生。"
            _save_state(state)
            await number_cmds[str(number)].finish(reply_message(event, text + "\n" + _render_current_floor_or_finish(state)))
        if node_type == "npc":
            reputation = int(state.get("flags", {}).get("start_reputation", 0))
            affinity = rpg_engine.npc_initial_affinity(reputation, character["random_stats"]["charm"], rng)
            npc_evt = rng.choice(rpg_data.EVENT_POOLS["npc"])
            state["flags"]["npc_affinity"] = affinity
            state["flags"]["pending_event"] = npc_evt
            state["status"] = "event_choice"
            _save_state(state)
            await number_cmds[str(number)].finish(reply_message(event, _render_event_choices(npc_evt)))

    if state["status"] == "inventory":
        inventory = state["character"].get("inventory", [])
        if number < 1 or number > len(inventory):
            await number_cmds[str(number)].finish(reply_message(event, "没有这个背包编号。"))
        entry = inventory[number - 1]
        item = rpg_engine.get_item_template(entry["id"])
        m = number_cmds[str(number)]
        # 技能书：局外学习（不走消耗品结算）
        if item.get("type") == "skillbook":
            character = state["character"]
            skill_id = str(item.get("effects", {}).get("learn_skill", ""))
            try:
                skill_name = rpg_engine.get_skill_template(skill_id)["name"]
            except ValueError:
                skill_name = skill_id
            ok, reason = rpg_engine.learn_skill(character, skill_id)
            if ok:
                _consume_entry(character, entry)
                state["character"] = character
                _save_state(state)
                lines = [f"📖 学会了技能【{skill_name}】！", "", rpg_renderer.render_skills(character),
                         "", rpg_renderer.render_inventory(character, in_page=True)]
                await m.finish(reply_message(event, "\n".join(lines)))
            if reason == "already_known":
                refund = max(1, int(item.get("price", 0)) // 2)
                _consume_entry(character, entry)
                character["gold"] = int(character.get("gold", 0)) + refund
                state["character"] = character
                _save_state(state)
                await m.finish(reply_message(
                    event,
                    f"你已经会【{skill_name}】了，把这本重复的书卖了换得 {refund} 金币。\n"
                    + rpg_renderer.render_inventory(character, in_page=True),
                ))
            # slots_full：不消耗，提示先遗忘
            await m.finish(reply_message(
                event,
                f"技能栏已满（{rpg_data.MAX_SKILL_SLOTS} 个），无法学习【{skill_name}】。\n"
                f"请先 /遗忘 <编号> 腾出位置：\n" + rpg_renderer.render_skills(character),
            ))
        rng = _rng_for_run(state, f"special:{number}:{datetime.now().timestamp()}")
        special_text = _handle_active_special_item(state, entry, item, rng)
        if special_text is not None:
            await m.finish(reply_message(event, special_text))
        if rpg_engine.is_special_item(item):
            await m.finish(reply_message(event, f"{item['name']} 是特殊道具：{item.get('description', '')}\n被动或收藏效果无需主动使用，通关后可带出局外背包。"))
        category = rpg_engine.item_category(item)
        if category == "equipment":
            await number_cmds[str(number)].finish(
                reply_message(event, f"{item['name']} 是装备，请发送 /装备 {number} 穿戴它。")
            )
        if category == "attribute":
            await number_cmds[str(number)].finish(
                reply_message(event, f"{item['name']} 是熟悉道具（饰品），持有即被动生效，无需主动使用。")
            )
        # 消耗品：局外使用，结算自身效果后扣除一件
        rng = _rng_for_run(state, f"useitem:{number}:{datetime.now().timestamp()}")
        character, eff_lines = rpg_engine.apply_consumable_effects(state["character"], item, rng)
        _consume_entry(character, entry)
        state["character"] = character
        _save_state(state)
        lines = [f"使用了 {item['name']}。", *eff_lines, "", rpg_renderer.render_inventory(character, in_page=True)]
        await number_cmds[str(number)].finish(reply_message(event, "\n".join(lines)))

    if state["status"] == "skill_select":
        skills = state["character"].get("skills", [])
        if number < 1 or number > len(skills):
            await number_cmds[str(number)].finish(reply_message(event, "没有这个技能编号。"))
        rng = _rng_for_run(state, f"skill:{number}:{datetime.now().timestamp()}")
        result = _battle_round(state, {"type": "skill", "skill_id": skills[number - 1]}, rng)
        await _finish_battle_round(event, number_cmds[str(number)], state, rng, result)

    if state["status"] == "item_select":
        consumables = rpg_engine.list_consumables(state["character"])
        if number < 1 or number > len(consumables):
            await number_cmds[str(number)].finish(reply_message(event, "没有这个道具编号。"))
        entry = consumables[number - 1]
        item = rpg_engine.get_item_template(entry["id"])
        rng = _rng_for_run(state, f"item:{number}:{datetime.now().timestamp()}")
        special_text = _handle_active_special_item(state, entry, item, rng)
        if special_text is not None:
            effect = rpg_engine.special_effect_id(item)
            if state.get("flags", {}).get("enemy") and effect not in {"battle_escape", "skip_floor", "rewind_round"}:
                followup = _enemy_followup_after_item(state, rng)
                followup["lines"] = [special_text, *followup.get("lines", [])]
                await _finish_battle_round(event, number_cmds[str(number)], state, rng, followup)
            await number_cmds[str(number)].finish(reply_message(event, special_text))
        if state["flags"].get("enemy"):  # 战斗中：使用道具占用一个回合，敌人随后行动
            result = _battle_round(state, {"type": "item", "item": item}, rng)
            if result.get("item_used"):
                _consume_entry(state["character"], entry)
            await _finish_battle_round(event, number_cmds[str(number)], state, rng, result)
        # 非战斗（理论上不会进入，保险处理）：直接结算效果
        _consume_entry(state["character"], entry)
        character, eff_lines = rpg_engine.apply_consumable_effects(state["character"], item, rng)
        state["character"] = character
        state["status"] = "battle"
        _save_state(state)
        await number_cmds[str(number)].finish(
            reply_message(event, "\n".join([f"使用了 {item['name']}。", *eff_lines]) + "\n" + _state_prompt(state))
        )

    if state["status"] == "event_choice":
        evt = state["flags"].get("pending_event")
        if not evt:
            state["status"] = "floor_select"
            _save_state(state)
            await number_cmds[str(number)].finish(reply_message(event, "事件已经结束了。"))
        options = evt.get("options", [])
        if number < 1 or number > len(options):
            await number_cmds[str(number)].finish(reply_message(event, "没有这个选项编号。"))
        option = options[number - 1]
        character = state["character"]
        opt_type = option.get("type", "effect")
        chapter = int(state.get("chapter", 0))
        rng = _rng_for_run(state, f"event:{evt['id']}:{number}:{datetime.now().timestamp()}")
        m = number_cmds[str(number)]

        # 条件 / 花费校验（不满足则保留事件、提示重选）
        if option.get("require", {}).get("consumable") and not rpg_engine.list_consumables(character):
            await m.finish(reply_message(event, "你没有可用的消耗品，请重新选择。"))
        gold_cost = int(option.get("cost", {}).get("gold", 0))
        if gold_cost > int(character.get("gold", 0)):
            await m.finish(reply_message(event, f"金币不足（需要 {gold_cost}G），请重新选择。"))
        if gold_cost:
            character["gold"] = int(character["gold"]) - gold_cost

        head = f"你选择了：{option['label']}"

        if opt_type == "leave":
            state["flags"].pop("pending_event", None)
            await m.finish(reply_message(event, head + "\n" + _render_current_floor_or_finish(state)))

        if opt_type == "open_shop":
            shop = option.get("shop", {})
            stock = rpg_engine.generate_npc_shop(
                rng, types=shop.get("types"), qualities=shop.get("qualities"),
                count=int(shop.get("count", 3)), price_mult=float(shop.get("price_mult", 1.0)),
                blind=bool(shop.get("blind")),
            )
            state["flags"].pop("pending_event", None)
            state["flags"]["shop_stock"] = stock
            state["flags"].pop("shop_discounted", None)  # 新店重置社交折扣资格
            state["flags"].pop("shop_social_used", None)  # 新店重置社交机会
            state["status"] = "shop"
            _save_state(state)
            await m.finish(reply_message(event, head + "\n" + rpg_renderer.render_shop(stock, int(character.get("gold", 0)))))

        if opt_type == "reveal":
            state["character"] = character
            state["flags"].pop("pending_event", None)
            await m.finish(reply_message(event, "\n".join([head, _peek_floor_types(state), _render_current_floor_or_finish(state)])))

        if opt_type == "sell":  # 出售：进入自选出售界面
            state["flags"].pop("pending_event", None)
            state["flags"]["sell_mult"] = float(option.get("mult", 0.6))
            state["status"] = "npc_sell"
            _save_state(state)
            await m.finish(reply_message(event, head + "\n" + _render_sell_list(character, state["flags"]["sell_mult"])))

        if opt_type == "bounty":  # 接赏金任务：立即进入战斗，胜利后结算奖励
            reward = rng.choice(option.get("rewards", [[]]))
            enemy = _build_social_battle(state, rng)
            state["flags"].pop("pending_event", None)
            state["flags"]["bounty_reward"] = reward
            state["flags"]["enemy"] = enemy
            state["status"] = "battle"
            _save_state(state)
            await _send_encounter(event, m, state, [head, "接下了任务，目标出现了！"])

        if opt_type == "social":  # 二级：选社交行为后再判定
            state["flags"]["pending_social"] = {
                "success": option.get("success", []),
                "fail": option.get("fail", []),
                "fail_battle": bool(option.get("fail_battle")),
                "then_sell": option.get("then_sell"),
                "label": option["label"],
            }
            state["flags"].pop("pending_event", None)
            state["status"] = "npc_social_choice"
            _save_state(state)
            await m.finish(reply_message(event, head + "\n请选择社交方式：\n1. 说服\n2. 欺骗\n3. 威吓\n发送 /<编号> 进行判定。"))

        # 默认：直接效果
        character, eff_lines = rpg_engine.resolve_event_effects(character, option.get("effects", []), chapter=chapter, rng=rng)
        state["character"] = character
        state["flags"].pop("pending_event", None)
        lines = [head]
        if gold_cost:
            lines.append(f"花费 {gold_cost} 金币。")
        lines.extend(eff_lines)
        lines.append(_render_current_floor_or_finish(state))
        await m.finish(reply_message(event, "\n".join(lines)))

    if state["status"] == "npc_social_choice":
        actions = {1: "说服", 2: "欺骗", 3: "威吓"}
        if number not in actions:
            await number_cmds[str(number)].finish(reply_message(event, "请发送 /1 说服、/2 欺骗 或 /3 威吓。"))
        ctx = state["flags"].get("pending_social", {})
        character = state["character"]
        affinity = int(state["flags"].get("npc_affinity", 0))
        chapter = int(state.get("chapter", 0))
        m = number_cmds[str(number)]
        rng = _rng_for_run(state, f"social:{number}:{datetime.now().timestamp()}")
        action = actions[number]
        result = rpg_engine.resolve_social_action(action, character, affinity, rng)
        _record_social_attempt(state, action, bool(result["success"]))
        state["flags"].pop("pending_social", None)
        state["flags"].pop("npc_affinity", None)
        lines = [f"【{action}】判定：d20={result['roll']}，成功率 {result['rate']:.1f}% —— " + ("成功！" if result["success"] else "失败。")]
        if result.get("charm_delta"):
            character.setdefault("base_random_stats", dict(character.get("random_stats", {})))
            character["base_random_stats"]["charm"] = int(character["base_random_stats"].get("charm", 0)) + int(result["charm_delta"])
            rpg_engine.recompute_character_stats(character)
            lines.append(f"魅力变化：{result['charm_delta']}。")
        then_sell = ctx.get("then_sell")
        if then_sell:  # 谈判类：判定后进入出售界面（成功更高回收价）
            mult = float(then_sell["success"] if result["success"] else then_sell["fail"])
            state["character"] = character
            state["flags"]["sell_mult"] = mult
            state["status"] = "npc_sell"
            _save_state(state)
            await m.finish(reply_message(event, "\n".join(lines) + "\n" + _render_sell_list(character, mult)))
        branch = ctx.get("success", []) if result["success"] else ctx.get("fail", [])
        character, eff_lines = rpg_engine.resolve_event_effects(character, branch, chapter=chapter, rng=rng)
        state["character"] = character
        lines.extend(eff_lines)
        if not result["success"] and (result.get("battle") or ctx.get("fail_battle")):
            enemy = _build_social_battle(state, rng)
            state["flags"]["enemy"] = enemy
            state["status"] = "battle"
            _save_state(state)
            lines.append("交涉破裂，引发了战斗！")
            await _send_encounter(event, m, state, lines)
        lines.append(_render_current_floor_or_finish(state))
        await m.finish(reply_message(event, "\n".join(lines)))

    if state["status"] == "npc_sell":
        sellable = _sellable_items(state["character"])
        if not sellable:
            state["status"] = "floor_select"
            _save_state(state)
            await number_cmds[str(number)].finish(reply_message(event, "没有可出售的道具了。\n" + _render_current_floor_or_finish(state)))
        if number < 1 or number > len(sellable):
            await number_cmds[str(number)].finish(reply_message(event, "没有这个道具编号。"))
        entry = sellable[number - 1]
        item = rpg_engine.get_item_template(entry["id"])
        mult = float(state["flags"].get("sell_mult", 0.6))
        price = max(1, round(int(item.get("price", 0)) * mult))
        character = state["character"]
        _consume_entry(character, entry)
        character["gold"] = int(character.get("gold", 0)) + price
        state["character"] = character
        _save_state(state)
        lines = [f"卖出 {item['name']}，获得 {price} 金币。"]
        remaining = _sellable_items(character)
        if remaining:
            lines.append("还想卖什么？（发送 /退出商店 结束）")
            lines.append(_render_sell_list(character, mult))
        else:
            state["flags"].pop("sell_mult", None)
            lines.append(_render_current_floor_or_finish(state))
        await number_cmds[str(number)].finish(reply_message(event, "\n".join(lines)))

    await number_cmds[str(number)].finish(reply_message(event, "当前状态不能使用编号选择。"))


for _index, _matcher in number_cmds.items():

    @_matcher.handle()
    async def _number_handler(event: MessageEvent, index: str = _index):
        await _handle_number(event, int(index))
