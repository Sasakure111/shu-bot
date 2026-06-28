"""QQ text rendering helpers for the fantasy roguelike RPG."""

from __future__ import annotations

from typing import Any

from . import rpg_data, rpg_engine


NODE_NAMES = {
    "battle": "战斗",
    "elite": "精英战斗",
    "npc": "社交事件",
    "shop": "商店",
    "mystery": "神秘事件",
    "rest": "休息点",
    "boss": "Boss",
}

RESULT_NAMES = {
    "victory": "通关",
    "death": "死亡",
    "rebirth": "转生",
    "abandon": "退出",
}

CATEGORY_TAGS = {
    "equipment": "装备",
    "attribute": "属性",
    "consumable": "消耗",
}


def _bar(current: int, maximum: int) -> str:
    return f"{current}/{maximum}"


def _item_name(item_id: str) -> str:
    try:
        return rpg_engine.get_item_template(item_id)["name"]
    except ValueError:
        return item_id


def _format_item_counts(item_ids: list[str]) -> str:
    counts: dict[str, int] = {}
    order: list[str] = []
    for item_id in item_ids:
        if item_id not in counts:
            order.append(item_id)
        counts[item_id] = counts.get(item_id, 0) + 1
    return "、".join(
        _item_name(item_id) if counts[item_id] == 1 else f"{_item_name(item_id)} x{counts[item_id]}"
        for item_id in order
    )


def _skill_name(skill_id: str) -> str:
    try:
        return rpg_engine.get_skill_template(skill_id)["name"]
    except ValueError:
        return skill_id


def _format_statuses(statuses: list[Any]) -> str:
    """状态可能是 {'id','duration'} 字典或旧版字符串，统一显示为 名称(剩余回合)。"""
    parts: list[str] = []
    for st in statuses:
        if isinstance(st, dict):
            defn = rpg_data.STATUS_DEFINITIONS.get(st.get("id", ""), {})
            name = st.get("name") or defn.get("name", st.get("id", "?"))
            stacks = int(st.get("stacks", 1))
            if stacks > 1:
                name = f"{name}×{stacks}"
            duration = st.get("duration")
            parts.append(f"{name}({duration})" if duration is not None else str(name))
        else:
            parts.append(str(st))
    return "、".join(parts) or "无"


def render_rules() -> str:
    return (
        "冒险规则简表\n"
        "发送 /冒险 开始进入模式选择。\n"
        "标准模式会选择固定职业，随后随机生成暴击、抗性、幸运、魅力。\n"
        "每层 GM 会给出 2~3 个编号选项，发送 /1、/2 这类编号进行选择。\n"
        "战斗中可用 /攻击、/技能、/道具、/逃跑。\n"
        "死亡或转生会以 0.5 倍结算局外奖励。"
    )


def render_adventure_entry(has_active_run: bool = False) -> str:
    if has_active_run:
        return "你已有一局冒险正在进行。发送当前可用指令继续，或使用 /查看面板、/查看背包。"
    return (
        "要开始神秘冒险吗！\n"
        "请选择模式：\n"
        "/标准模式 - 固定职业，完整奖励\n"
        "/创意模式 - 暂未开放，占位中"
    )


def render_mode_intro() -> str:
    return (
        "标准模式简介：\n"
        "从 6 个固定职业中选择其一，随机生成四项骰子属性，完成三章冒险。\n"
        "通关后会根据局内经验、金币、魅力结算局外经验和声望。"
    )


def render_standard_menu() -> str:
    return "标准模式\n/创建角色 - 查看职业池\n/模式简介 - 查看模式说明\n/返回 - 回到上一级"


def render_creative_placeholder() -> str:
    return "创意模式还在施工中。当前请先使用 /标准模式。"


def render_class_choices() -> str:
    lines = ["请选择职业："]
    for index, template in enumerate(rpg_data.STANDARD_CLASSES, 1):
        base = template["base"]
        lines.append(
            f"{index}. {template['name']} - {template['description']}\n"
            f"   HP {base['hp']} ATK {base['atk']} DEF {base['def']} "
            f"MAT {base['mat']} MDF {base['mdf']} MP {base['mp']} SPD {base['spd']}"
        )
    lines.append("发送 /选择职业 <职业名>，例如 /选择职业 战士。也可以发送 /随机创角。")
    return "\n".join(lines)


def render_random_stats(character: dict[str, Any]) -> str:
    stats = character["random_stats"]
    total_crit = int(rpg_engine.effective_crit_rate(character))
    total_resist = int(rpg_engine.total_resist(character))
    return (
        "骰子属性已生成（d20）：\n"
        f"暴击：骰子 {stats['crit']} → 总暴击率 {total_crit}%\n"
        f"抗性：骰子 {stats['resist']} → 总抗性 {total_resist}%\n"
        f"幸运：{stats['luck']}\n"
        f"魅力：{stats['charm']}\n"
        "发送 /重新分配 可重新随机，发送 /开始冒险 确认出发。"
    )


def render_character_card(character: dict[str, Any]) -> str:
    stats = character["stats"]
    random_stats = character["random_stats"]
    next_exp = rpg_engine.exp_to_next_level(int(character["level"]))
    next_text = "MAX" if next_exp is None else f"{character['exp']} / {next_exp}"
    skills = "、".join(_skill_name(skill_id) for skill_id in character.get("skills", [])) or "无"
    equipment = "、".join(_item_name(entry["id"]) for entry in character.get("equipment", [])) or "无"
    background = character.get("background") or "暂无"
    return (
        f"【职业】{character['class_name']} Lv.{character['level']}（{next_text}）\n"
        f"【描述】{character.get('description', '')}\n\n"
        "【属性】\n"
        f"HP 血量：{_bar(character['current_hp'], stats['hp'])}\n"
        f"ATK 攻击：{stats['atk']}      DEF 防御：{stats['def']}\n"
        f"MAT 魔攻：{stats['mat']}      MDF 魔防：{stats['mdf']}\n"
        f"MP 魔力：{_bar(character['current_mp'], stats['mp'])}\n"
        f"SPD 攻速：{stats['spd']}      总抗性：{int(rpg_engine.total_resist(character))}%\n\n"
        "【骰子随机属性】\n"
        f"总暴击率：{int(rpg_engine.effective_crit_rate(character))}%（骰子 {random_stats['crit']}）\n"
        f"幸运：{random_stats['luck']}      魅力：{random_stats['charm']}\n\n"
        f"【金币】{character.get('gold', 0)}\n"
        f"【状态】{_format_statuses(character.get('statuses', []))}\n"
        + (f"【局内状态】{'、'.join(character.get('run_statuses', []))}\n" if character.get("run_statuses") else "")
        + f"【装备】{equipment}\n"
        f"【技能】{skills}\n"
        f"【背景】{background}"
    )


def render_outside_player_profile(
    player: dict[str, Any],
    *,
    player_name: str,
    next_exp: int | None,
    gm_welcome: str,
) -> str:
    exp_text = "MAX" if next_exp is None else f"{int(player['exp'])} / {next_exp}"
    return (
        f"【冒险者】 <{player_name}>\n"
        f"【等级】 Lv. {int(player['level'])}（{exp_text}）\n"
        f"【声望】{player['title']} ：{int(player['reputation'])}\n\n"
        "【背包】\n"
        "*使用 /背包 查看详情。\n"
        "【成就】\n"
        "*使用 /成就书 查看成就。\n\n"
        f"AI GM：{gm_welcome}"
    )


def render_outside_inventory(items: list[Any]) -> str:
    lines = ["【局外背包】", "容量：无上限"]
    if not items:
        lines.append("背包为空。通关后可带出特殊道具和 Boss 纪念品。")
        return "\n".join(lines)

    for index, row in enumerate(items, 1):
        item_id = row["item_id"]
        quantity = int(row["quantity"])
        try:
            item = rpg_engine.get_item_template(item_id)
            name = item["name"]
            item_type = item.get("type", "item")
            description = item.get("description", "")
        except ValueError:
            name = str(item_id)
            item_type = "未知"
            description = "旧版本收藏品。"
        lines.append(f"{index}. [{item_type}] {name} x{quantity}")
        if description:
            lines.append(f"   {description}")
    return "\n".join(lines)


def render_achievement_book(unlocked_ids: set[str], *, player_name: str) -> str:
    from . import rpg_achievements

    total = len(rpg_achievements.ACHIEVEMENTS)
    got = sum(1 for a in rpg_achievements.ACHIEVEMENTS if a["id"] in unlocked_ids)
    lines = [
        f"【成就书】 <{player_name}>",
        f"进度：{got} / {total}",
        "",
    ]
    for ach in rpg_achievements.ACHIEVEMENTS:
        unlocked = ach["id"] in unlocked_ids
        mark = "✅" if unlocked else "🔒"
        if ach["hidden"] and not unlocked:
            # 隐藏成就未解锁：不剧透名称与条件
            lines.append(f"{mark} #{ach['id']} 【隐藏成就】 ？？？")
            continue
        name = ("【隐藏】" if ach["hidden"] else "") + ach["name"]
        lines.append(f"{mark} #{ach['id']} {name}")
        lines.append(f"    {ach['desc']}")
    return "\n".join(lines)


def render_background_ready(character: dict[str, Any]) -> str:
    return (
        f"AI GM 为 {character['class_name']} 写下了开场背景：\n"
        f"{character.get('background') or '你带着尚未被讲述的过去，踏进了这场奇幻冒险。'}\n\n"
        "冒险开始。下一条消息将显示第一层选项。"
    )


def render_floor_choices(
    run_map: dict[str, Any],
    chapter_index: int,
    floor_index: int,
) -> str:
    chapter = run_map["chapters"][chapter_index]
    floor = chapter["floors"][floor_index]
    total_floors = len(chapter["floors"])
    lines = [f"{chapter['name']} 第 {floor['index']} / {total_floors} 层"]
    for choice in floor["choices"]:
        node_name = NODE_NAMES.get(choice["type"], choice["type"])
        if choice["type"] == "boss":
            boss = rpg_engine.get_boss_template(choice["boss_id"])
            node_name = f"Boss：{boss['name']}"
        lines.append(f"{choice['index']}：{node_name}")
    lines.append("发送 /<编号> 选择事件，例如 /1。")
    lines.append("可用：/查看背包 /查看面板 /装备 /卸下 /遗忘 /转生")
    return "\n".join(lines)


def render_inventory(character: dict[str, Any], in_page: bool = False) -> str:
    inventory = character.get("inventory", [])
    equipment = character.get("equipment", [])
    lines = [
        f"背包 {len(inventory)}/{rpg_engine.inventory_backpack_slots(character)} | 金币：{character.get('gold', 0)}"
    ]
    if equipment:
        worn = "、".join(f"{i}.{_item_name(entry['id'])}" for i, entry in enumerate(equipment, 1))
    else:
        worn = "空"
    lines.append(f"装备栏 {len(equipment)}/{rpg_data.MAX_EQUIPPED}：{worn}")
    if not inventory:
        lines.append("背包为空。")
    else:
        for index, entry in enumerate(inventory, 1):
            item = rpg_engine.get_item_template(entry["id"])
            if item.get("type") == "skillbook":
                tag = "技能书"
            elif rpg_engine.is_special_item(item):
                tag = "特殊"
            else:
                tag = CATEGORY_TAGS.get(rpg_engine.item_category(item), "道具")
            lines.append(
                f"{index}. [{tag}] {item['name']} x{entry.get('quantity', 1)} - {item.get('description', '')}"
            )
    lines.append("可用：/装备 <编号> /卸下 <编号>")
    if in_page:
        # 背包二级页：明确局外用法，并提示这是独立页面、需 /返回 退出
        lines.append("局外使用：发送 /<编号> 使用对应编号的【消耗】道具，或翻阅【技能书】学会技能。")
        lines.append("【属性】道具（饰品）持有即被动生效，无需主动使用；【装备】请用 /装备 <编号> 穿戴。")
        lines.append("发送 /返回 收起背包，回到当前层继续冒险。")
    return "\n".join(lines)


def render_battle_state(character: dict[str, Any], enemy: dict[str, Any]) -> str:
    cstats = character["stats"]
    estats = enemy["stats"]
    cst = character.get("statuses", [])
    est = enemy.get("statuses", [])
    player_status = f"｜状态：{_format_statuses(cst)}" if cst else ""
    enemy_status = f"｜状态：{_format_statuses(est)}" if est else ""
    return (
        f"遭遇 {enemy['rank_name']} 敌人：{enemy['name']} Lv.{enemy['level']}\n"
        f"你：HP {_bar(character['current_hp'], cstats['hp'])} | MP {_bar(character['current_mp'], cstats['mp'])}{player_status}\n"
        f"敌：HP {_bar(enemy['current_hp'], estats['hp'])} | MP {_bar(enemy['current_mp'], estats['mp'])}{enemy_status}\n"
        "可用：/攻击 /技能 /道具 /逃跑"
    )


def render_attack_result(attacker_name: str, defender_name: str, result: dict[str, Any]) -> str:
    if result.get("dodged"):
        text = f"{defender_name} 闪避了 {attacker_name} 的攻击。"
    else:
        crit = "暴击！" if result.get("critical") else ""
        text = f"{attacker_name} {crit}对 {defender_name} 造成 {result['damage']} 点伤害。"
    if result.get("defeated"):
        text += f"\n{defender_name} 被击败了。"
    return text


def render_skills(character: dict[str, Any]) -> str:
    """技能栏一览（带编号，供 /遗忘 与学习反馈使用）。"""
    skills = character.get("skills", [])
    lines = [f"技能栏 {len(skills)}/{rpg_data.MAX_SKILL_SLOTS}："]
    if not skills:
        lines.append("（空）")
    for index, skill_id in enumerate(skills, 1):
        try:
            skill = rpg_engine.get_skill_template(skill_id)
        except ValueError:
            lines.append(f"{index}. {skill_id}")
            continue
        innate = "（出生技）" if skill.get("innate") else ""
        lines.append(
            f"{index}. {skill['name']}{innate} | MP{skill.get('mp_cost', 0)} | {skill.get('description', '')}"
        )
    return "\n".join(lines)


def render_skill_list(character: dict[str, Any]) -> str:
    skills = character.get("skills", [])
    if not skills:
        return "你还没有可用技能。发送 /返回 回到战斗。"
    lines = ["请选择技能："]
    for index, skill_id in enumerate(skills, 1):
        skill = rpg_engine.get_skill_template(skill_id)
        lines.append(f"{index}. {skill['name']} | MP {skill.get('mp_cost', 0)} | {skill.get('description', '')}")
    lines.append("发送 /<编号> 使用技能，或 /返回 回到战斗。")
    return "\n".join(lines)


def render_item_list(character: dict[str, Any]) -> str:
    consumables = rpg_engine.list_consumables(character)
    if not consumables:
        return "没有可在战斗中使用的消耗品。发送 /返回 回到战斗。"
    lines = ["请选择道具："]
    for index, entry in enumerate(consumables, 1):
        item = rpg_engine.get_item_template(entry["id"])
        lines.append(f"{index}. {item['name']} x{entry.get('quantity', 1)} | {item.get('description', '')}")
    lines.append("发送 /<编号> 使用道具，或 /返回 回到战斗。")
    return "\n".join(lines)


def render_shop(stock: list[dict[str, Any]], gold: int) -> str:
    lines = [f"商店 | 你的金币：{gold}"]
    for index, item in enumerate(stock, 1):
        quality = rpg_data.ITEM_QUALITY_NAMES.get(item.get("quality", ""), item.get("quality", ""))
        if item.get("blind"):  # 盲盒：只显示稀有度
            lines.append(f"{index}. [{quality}] ？？？ - {item['final_price']} 金\n   买下后才知道是什么。")
            continue
        lines.append(
            f"{index}. [{quality}] {item['name']} - {item['final_price']} 金\n"
            f"   {item.get('description', '')}"
        )
    lines.append("可用：/购买 <编号> /退出商店")
    lines.append("社交：/说服 /欺骗 /威吓（成功可压价，欺骗、威吓失败会被赶出商店）")
    return "\n".join(lines)


def render_reward(reward: dict[str, Any]) -> str:
    lines = [f"获得经验 {reward.get('exp', 0)}，金币 {reward.get('gold', 0)}。"]
    item = reward.get("item")
    if item:
        if reward.get("item_lost"):
            lines.append(f"掉落了 {item['name']}，但背包已满，遗失了。")
        else:
            lines.append(f"获得道具：{item['name']}。")
    carry_out = reward.get("carry_out", [])
    if carry_out:
        lines.append("可带出收藏：" + _format_item_counts(carry_out))
    return "\n".join(lines)


def render_confirm(action: str) -> str:
    return f"是否确认{action}？发送 /是 确认，/否 取消。"


def render_final_rewards(final_rewards: dict[str, Any]) -> str:
    result_name = RESULT_NAMES.get(final_rewards["result"], final_rewards["result"])
    multiplier = final_rewards["multiplier"]
    lines = [
        f"本局结束：{result_name}",
        f"结算倍率：{multiplier:g}x",
        f"局内经验：{final_rewards['run_exp']}",
        f"局内金币：{final_rewards['run_gold']}",
        f"最终魅力：{final_rewards['charm']}",
        f"获得局外玩家经验：{final_rewards['outside_exp']}",
        f"获得局外声望：{final_rewards['outside_reputation']}",
    ]
    outside_player = final_rewards.get("outside_player")
    if outside_player:
        next_exp = outside_player.get("next_exp")
        exp_text = "MAX" if next_exp is None else f"{outside_player['exp']} / {next_exp}"
        lines.append(f"局外玩家等级：Lv.{outside_player['level']}（{exp_text}）")
        lines.append(f"局外声望：{outside_player['reputation']}（{outside_player.get('title', '籍籍无名')}）")
    carry_out = final_rewards.get("carry_out_items", [])
    if carry_out:
        lines.append("带出局外收藏：" + _format_item_counts(carry_out))
    return "\n".join(lines)
