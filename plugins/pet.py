from __future__ import annotations

import random
import os
from datetime import date, datetime, timedelta

from dotenv import load_dotenv
from nonebot import get_bot, on_command, require
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent, MessageSegment
from nonebot.params import CommandArg
from openai import OpenAI

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

from .database import (
    MAX_PET_LEVEL,
    add_pet_affection,
    add_pet_exp,
    add_pet_reward,
    consume_daily_pet_interaction,
    create_pet_for_user,
    ensure_broadcast_target,
    ensure_current_pet,
    exp_to_next_level,
    get_enabled_broadcast_targets,
    get_last_battle_challenge_at,
    get_last_played_at,
    get_pet_type,
    get_random_pet_type_by_rarity,
    get_random_special_pet_type,
    list_user_pets,
    mark_daily_checkin,
    set_broadcast_enabled,
    set_last_battle_challenge_at,
    set_last_played_at,
    switch_current_pet,
)
from .message_utils import reply_message, should_ignore_group_message

load_dotenv(".env.prod")

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL"),
)

CHECKIN_EXP = 30
CHECKIN_AFFECTION = 2
PLAY_EXP = 12
PLAY_AFFECTION = 3
INTERACT_MIN_AFFECTION = 20
INTERACT_DAILY_LIMIT = 10
PLAY_COOLDOWN = timedelta(hours=1)
BATTLE_CHALLENGE_COOLDOWN = timedelta(minutes=10)
WILD_EXPIRE_MINUTES = 10
WILD_BROADCAST_MIN_MINUTES = 10
WILD_BROADCAST_MAX_MINUTES = 60
BOSS_EXPIRE_MINUTES = 15
BOSS_REWARD_EXP = 90
BOSS_REWARD_AFFECTION = 8
BOSS_SPECIAL_REWARD_RATE = 18
BATTLE_REWARD_EXP = 24
BATTLE_WIN_AFFECTION = 4
BATTLE_LOSE_AFFECTION = -3
BATTLE_CHALLENGE_EXPIRE_MINUTES = 5
RARITY_SPAWN_WEIGHTS = [(1, 45), (2, 28), (3, 16), (4, 8), (5, 3)]
BOSS_NAMES = ["裂隙巨兽", "熔岩暴君", "幽潮领主", "星骸魔像"]

active_wild_pets: dict[str, dict[str, object]] = {}
active_group_bosses: dict[int, dict[str, object]] = {}
pending_battles: dict[int, dict[str, object]] = {}
next_wild_broadcast_at = datetime.now() + timedelta(
    minutes=random.randint(WILD_BROADCAST_MIN_MINUTES, WILD_BROADCAST_MAX_MINUTES)
)


def rarity_stars(rarity: int) -> str:
    return "★" * int(rarity)


def pet_level_text(level: int) -> str:
    return "MAX" if int(level) >= MAX_PET_LEVEL else str(level)


def context_from_event(event: MessageEvent) -> tuple[str, int, str]:
    if isinstance(event, GroupMessageEvent):
        return "group", int(event.group_id), f"group:{event.group_id}"
    return "private", int(event.user_id), f"private:{event.user_id}"


def ensure_default_broadcast_for_event(event: MessageEvent) -> None:
    target_type, target_id, _ = context_from_event(event)
    ensure_broadcast_target(target_type, target_id)


def format_pet_status(pet) -> str:
    level = int(pet["level"])
    next_exp = exp_to_next_level(pet)
    exp_text = "MAX" if next_exp is None else f"{pet['exp']}/{next_exp}"
    return (
        f"🐾 当前宠物: {pet['name']} {rarity_stars(pet['rarity'])}\n"
        f"等级: {pet_level_text(level)}\n"
        f"经验: {exp_text}\n"
        f"血量: {pet['hp']} | 攻击: {pet['attack']} | 速度: {pet['speed']}\n"
        f"好感度: {pet['affection']}"
    )


def format_pet_list(pets) -> str:
    if not pets:
        return "仓库里还没有宠物，先发送 /我的宠物 领取初始宠物吧。"

    lines = [f"📦 宠物仓库（共 {len(pets)} 只）"]
    for pet in pets:
        marker = "  当前" if int(pet["id"]) == int(pet["current_pet_id"]) else ""
        next_exp = exp_to_next_level(pet)
        exp_text = "MAX" if next_exp is None else f"{pet['exp']}/{next_exp}"
        lines.append(
            f"ID {pet['id']} | {pet['name']} {rarity_stars(pet['rarity'])} "
            f"| Lv.{pet_level_text(pet['level'])} | EXP {exp_text} "
            f"| HP {pet['hp']} ATK {pet['attack']} SPD {pet['speed']} "
            f"| 好感 {pet['affection']}{marker}"
        )
    lines.append("使用 /切换宠物 <宠物id> 切换当前携带宠物。")
    return "\n".join(lines)


def random_wild_pet_type():
    rarities = [item[0] for item in RARITY_SPAWN_WEIGHTS]
    weights = [item[1] for item in RARITY_SPAWN_WEIGHTS]
    rarity = random.choices(rarities, weights=weights, k=1)[0]
    return get_random_pet_type_by_rarity(rarity)


def capture_rate(carried_pet) -> int:
    base = 50 + (int(carried_pet["rarity"]) - 1) * 8
    level_bonus = (int(carried_pet["level"]) - 1) * 2
    return min(95, base + level_bonus)


def pet_max_hp(pet) -> int:
    return int(pet["hp"]) + (int(pet["level"]) - 1) * 8


def pet_attack_power(pet) -> int:
    return int(pet["attack"]) + (int(pet["level"]) - 1) * 3 + int(pet["affection"]) // 20


def pet_speed_value(pet) -> int:
    return int(pet["speed"]) + (int(pet["level"]) - 1) * 2


def parse_at_user(message: Message) -> int | None:
    for segment in message:
        if segment.type == "at":
            qq = segment.data.get("qq")
            if qq and str(qq).isdigit():
                return int(qq)
    return None


def build_battle_pet(user_id: int) -> dict[str, object]:
    pet = ensure_current_pet(user_id)
    return {
        "user_id": int(user_id),
        "pet": pet,
        "hp": pet_max_hp(pet),
        "max_hp": pet_max_hp(pet),
        "attack": pet_attack_power(pet),
        "speed": pet_speed_value(pet),
    }


def simulate_pet_battle(challenger_id: int, defender_id: int) -> tuple[int, list[str]]:
    left = build_battle_pet(challenger_id)
    right = build_battle_pet(defender_id)
    first, second = (left, right) if int(left["speed"]) >= int(right["speed"]) else (right, left)
    logs = [
        f"{first['pet']['name']} 速度更快，率先出手。",
    ]

    for round_no in range(1, 31):
        for attacker, defender in ((first, second), (second, first)):
            critical = random.randint(1, 100) <= 10
            damage = int(attacker["attack"]) * (2 if critical else 1)
            defender["hp"] = max(0, int(defender["hp"]) - damage)
            crit_text = "暴击！" if critical else ""
            if round_no <= 8:
                logs.append(
                    f"第 {round_no} 回合：{attacker['pet']['name']} {crit_text}造成 {damage} 伤害，"
                    f"{defender['pet']['name']} 剩余 {defender['hp']}/{defender['max_hp']}。"
                )
            if int(defender["hp"]) <= 0:
                return int(attacker["user_id"]), logs

    winner = int(left["user_id"]) if int(left["hp"]) >= int(right["hp"]) else int(right["user_id"])
    logs.append("战斗达到回合上限，按剩余血量判定胜负。")
    return winner, logs


def build_exp_result(prefix: str, pet, leveled: int) -> str:
    lines = [prefix]
    if leveled > 0:
        lines.append(f"{pet['name']} 升级了 {leveled} 级，现在是 Lv.{pet_level_text(pet['level'])}！")
    lines.append(format_pet_status(pet))
    return "\n".join(lines)


def affection_stage(affection: int) -> str:
    if affection >= 80:
        return "非常亲密，像最信任的伙伴"
    if affection >= 50:
        return "亲近，会主动撒娇和回应"
    return "有些熟悉，愿意靠近但还带着试探"


def build_pet_interaction(pet) -> str:
    affection = int(pet["affection"])
    prompt = (
        "请描写一段用户与当前携带宠物互动的中文场景。"
        "要求：用户用“你”指代，宠物必须用宠物名字指代；"
        "不要写成对话剧本，不要超过100字；"
        "好感度越高互动越亲密，但保持温暖可爱。"
        f"宠物名：{pet['name']}；好感度：{affection}/100；亲密程度：{affection_stage(affection)}。"
    )
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "你是宠物互动场景描写助手，输出简短、具体、有画面感。"},
            {"role": "user", "content": prompt},
        ],
        max_tokens=120,
    )
    return response.choices[0].message.content.strip()[:100]


async def send_wild_pet(bot: Bot, target_type: str, target_id: int) -> None:
    pet_type = random_wild_pet_type()
    if pet_type is None:
        return

    context_key = f"{target_type}:{target_id}"
    expires_at = datetime.now() + timedelta(minutes=WILD_EXPIRE_MINUTES)
    active_wild_pets[context_key] = {
        "type_id": int(pet_type["id"]),
        "expires_at": expires_at,
    }

    message = (
        f"🌿 野生宠物出现了！\n"
        f"{pet_type['name']} {rarity_stars(pet_type['rarity'])}\n"
        f"发送 /捕捉 试试看吧，{WILD_EXPIRE_MINUTES} 分钟后它就会离开。"
    )

    try:
        if target_type == "group":
            await bot.send_group_msg(group_id=target_id, message=message)
        else:
            await bot.send_private_msg(user_id=target_id, message=message)
    except Exception as exc:
        print(f"[PET] 野生宠物播报失败: {target_type}:{target_id} {type(exc).__name__}: {exc}")


async def send_group_boss(bot: Bot, group_id: int) -> None:
    if group_id in active_group_bosses:
        return

    name = random.choice(BOSS_NAMES)
    max_hp = random.randint(520, 760)
    expires_at = datetime.now() + timedelta(minutes=BOSS_EXPIRE_MINUTES)
    active_group_bosses[group_id] = {
        "name": name,
        "hp": max_hp,
        "max_hp": max_hp,
        "expires_at": expires_at,
        "participants": set(),
        "damage": {},
    }
    await bot.send_group_msg(
        group_id=group_id,
        message=(
            f"⚔️ 公屏 Boss 出现：{name}\n"
            f"血量: {max_hp}/{max_hp}\n"
            f"限时 {BOSS_EXPIRE_MINUTES} 分钟，@我并发送 /讨伐 参与挑战！"
        ),
    )


async def expire_group_bosses() -> None:
    if not active_group_bosses:
        return

    bot = get_bot()
    now = datetime.now()
    expired_group_ids = [
        group_id
        for group_id, boss in active_group_bosses.items()
        if now >= boss["expires_at"]
    ]
    for group_id in expired_group_ids:
        boss = active_group_bosses.pop(group_id, None)
        if boss is None:
            continue
        try:
            await bot.send_group_msg(
                group_id=group_id,
                message=f"💨 {boss['name']} 逃跑了，本次讨伐失败，没有奖励。",
            )
        except Exception as exc:
            print(f"[PET] Boss 逃跑播报失败: group:{group_id} {type(exc).__name__}: {exc}")


async def expire_battle_challenges() -> None:
    if not pending_battles:
        return

    bot = get_bot()
    now = datetime.now()
    expired_group_ids = [
        group_id
        for group_id, challenge in pending_battles.items()
        if now >= challenge["expires_at"]
    ]
    for group_id in expired_group_ids:
        challenge = pending_battles.pop(group_id, None)
        if challenge is None:
            continue
        try:
            await bot.send_group_msg(
                group_id=group_id,
                message=(
                    f"对战挑战已超时取消："
                    f"{challenge['challenger_id']} -> {challenge['defender_id']}"
                ),
            )
        except Exception as exc:
            print(f"[PET] 对战超时播报失败: group:{group_id} {type(exc).__name__}: {exc}")


def build_boss_reward_text(participants: set[int]) -> str:
    lines = [
        f"Boss 被击败了！参与讨伐的 {len(participants)} 位用户获得奖励：",
        f"出战宠物 +{BOSS_REWARD_EXP} 经验，+{BOSS_REWARD_AFFECTION} 好感度。",
    ]
    special_rewards = []
    for user_id in participants:
        add_pet_reward(user_id, BOSS_REWARD_EXP, BOSS_REWARD_AFFECTION)
        if random.randint(1, 100) <= BOSS_SPECIAL_REWARD_RATE:
            pet_type = get_random_special_pet_type()
            if pet_type is not None:
                create_pet_for_user(user_id, int(pet_type["id"]))
                special_rewards.append(f"{user_id} 获得特殊宠物 {pet_type['name']} {rarity_stars(pet_type['rarity'])}")

    if special_rewards:
        lines.append("特殊奖励：")
        lines.extend(special_rewards)
    else:
        lines.append("这次没有掉落特殊宠物。")
    return "\n".join(lines)


def reset_next_wild_broadcast_time() -> None:
    global next_wild_broadcast_at
    next_wild_broadcast_at = datetime.now() + timedelta(
        minutes=random.randint(WILD_BROADCAST_MIN_MINUTES, WILD_BROADCAST_MAX_MINUTES)
    )


@scheduler.scheduled_job("interval", minutes=1, id="pet_wild_broadcast")
async def pet_wild_broadcast() -> None:
    if datetime.now() < next_wild_broadcast_at:
        return

    reset_next_wild_broadcast_time()
    targets = get_enabled_broadcast_targets()
    if not targets:
        return

    bot = get_bot()
    for target in targets:
        await send_wild_pet(bot, target["target_type"], int(target["target_id"]))


@scheduler.scheduled_job("interval", minutes=120, id="pet_group_boss_broadcast")
async def pet_group_boss_broadcast() -> None:
    targets = [
        target
        for target in get_enabled_broadcast_targets()
        if target["target_type"] == "group"
    ]
    if not targets:
        return

    bot = get_bot()
    for target in targets:
        try:
            await send_group_boss(bot, int(target["target_id"]))
        except Exception as exc:
            print(f"[PET] Boss 播报失败: group:{target['target_id']} {type(exc).__name__}: {exc}")


@scheduler.scheduled_job("interval", minutes=1, id="pet_boss_expire_check")
async def pet_boss_expire_check() -> None:
    await expire_group_bosses()
    await expire_battle_challenges()


my_pet_cmd = on_command("我的宠物", priority=4, block=True)


@my_pet_cmd.handle()
async def handle_my_pet(event: MessageEvent):
    if should_ignore_group_message(event):
        return

    ensure_default_broadcast_for_event(event)
    pet = ensure_current_pet(event.user_id)
    await my_pet_cmd.finish(reply_message(event, format_pet_status(pet)))


warehouse_cmd = on_command("查看仓库", priority=4, block=True)


@warehouse_cmd.handle()
async def handle_warehouse(event: MessageEvent):
    if should_ignore_group_message(event):
        return

    ensure_default_broadcast_for_event(event)
    ensure_current_pet(event.user_id)
    pets = list_user_pets(event.user_id)
    await warehouse_cmd.finish(reply_message(event, format_pet_list(pets)))


switch_pet_cmd = on_command("切换宠物", priority=4, block=True)


@switch_pet_cmd.handle()
async def handle_switch_pet(event: MessageEvent, args: Message = CommandArg()):
    if should_ignore_group_message(event):
        return

    ensure_default_broadcast_for_event(event)
    pet_id_text = args.extract_plain_text().strip()
    if not pet_id_text:
        await switch_pet_cmd.finish(reply_message(event, "用法: /切换宠物 <宠物id>\n可以先用 /查看仓库 查看宠物 ID。"))

    try:
        pet_id = int(pet_id_text)
    except ValueError:
        await switch_pet_cmd.finish(reply_message(event, "宠物 ID 需要是数字。可以先用 /查看仓库 查看。"))

    pet = switch_current_pet(event.user_id, pet_id)
    if pet is None:
        await switch_pet_cmd.finish(reply_message(event, "找不到这只宠物，或者它不在你的仓库里。"))

    await switch_pet_cmd.finish(
        reply_message(
            event,
            f"已切换当前携带宠物: {pet['name']} {rarity_stars(pet['rarity'])}\n"
            f"等级: {pet_level_text(pet['level'])}",
        )
    )


checkin_cmd = on_command("打卡", priority=4, block=True)


@checkin_cmd.handle()
async def handle_checkin(event: MessageEvent):
    if should_ignore_group_message(event):
        return

    ensure_default_broadcast_for_event(event)
    today = date.today().isoformat()
    if not mark_daily_checkin(event.user_id, today):
        await checkin_cmd.finish(reply_message(event, "今天已经打过卡啦，明天再来摸摸宠物吧。"))

    pet, leveled = add_pet_reward(event.user_id, CHECKIN_EXP, CHECKIN_AFFECTION)
    await checkin_cmd.finish(
        reply_message(
            event,
            build_exp_result(
                f"打卡成功！宠物获得 {CHECKIN_EXP} 点经验，增加 {CHECKIN_AFFECTION} 点好感度。",
                pet,
                leveled,
            ),
        )
    )


play_cmd = on_command("玩耍", priority=4, block=True)


@play_cmd.handle()
async def handle_play(event: MessageEvent):
    if should_ignore_group_message(event):
        return

    ensure_default_broadcast_for_event(event)
    now = datetime.now()
    last_played_at = get_last_played_at(event.user_id)

    if last_played_at:
        last_played = datetime.fromisoformat(last_played_at)
        next_play = last_played + PLAY_COOLDOWN
        if now < next_play:
            minutes = max(1, int((next_play - now).total_seconds() // 60) + 1)
            await play_cmd.finish(reply_message(event, f"宠物刚玩累了，还要休息约 {minutes} 分钟。"))

    set_last_played_at(event.user_id, now.isoformat(timespec="seconds"))
    pet, leveled = add_pet_reward(event.user_id, PLAY_EXP, PLAY_AFFECTION)
    await play_cmd.finish(
        reply_message(
            event,
            build_exp_result(
                f"你和宠物玩了一会儿，获得 {PLAY_EXP} 点经验，增加 {PLAY_AFFECTION} 点好感度。",
                pet,
                leveled,
            ),
        )
    )


interact_cmd = on_command("互动", priority=4, block=True)


@interact_cmd.handle()
async def handle_interact(event: MessageEvent):
    if should_ignore_group_message(event):
        return

    ensure_default_broadcast_for_event(event)
    pet = ensure_current_pet(event.user_id)
    affection = int(pet["affection"])
    if affection <= INTERACT_MIN_AFFECTION:
        await interact_cmd.finish(
            reply_message(
                event,
                f"{pet['name']} 还没有完全放下戒心。好感度需要超过 {INTERACT_MIN_AFFECTION} 才能互动，当前是 {affection}/100。",
            )
        )

    used_count = consume_daily_pet_interaction(
        event.user_id,
        date.today().isoformat(),
        INTERACT_DAILY_LIMIT,
    )
    if used_count is None:
        await interact_cmd.finish(
            reply_message(event, f"今天的互动次数已经用完啦，每天最多 {INTERACT_DAILY_LIMIT} 次。")
        )

    try:
        interaction = build_pet_interaction(pet)
    except Exception as exc:
        print(f"[PET] 互动生成失败: {type(exc).__name__}: {exc}")
        interaction = f"你轻轻靠近{pet['name']}，它抬头看了看你，慢慢贴过来蹭了蹭你的手心。"

    await interact_cmd.finish(
        reply_message(event, f"{interaction}\n今日互动次数: {used_count}/{INTERACT_DAILY_LIMIT}")
    )


capture_cmd = on_command("捕捉", priority=4, block=True)


@capture_cmd.handle()
async def handle_capture(event: MessageEvent):
    if should_ignore_group_message(event):
        return

    ensure_default_broadcast_for_event(event)
    _, _, context_key = context_from_event(event)
    wild = active_wild_pets.get(context_key)

    if wild is None or datetime.now() >= wild["expires_at"]:
        active_wild_pets.pop(context_key, None)
        await capture_cmd.finish(reply_message(event, "附近暂时没有野生宠物，等下一次播报吧。"))

    carried_pet = ensure_current_pet(event.user_id)
    rate = capture_rate(carried_pet)
    pet_type = get_pet_type(int(wild["type_id"]))
    if pet_type is None:
        active_wild_pets.pop(context_key, None)
        await capture_cmd.finish(reply_message(event, "这只野生宠物已经跑远了。"))

    active_wild_pets.pop(context_key, None)
    if random.randint(1, 100) <= rate:
        create_pet_for_user(event.user_id, int(pet_type["id"]), set_current=True)
        await capture_cmd.finish(
            reply_message(
                event,
                f"捕捉成功！你获得并携带了 {pet_type['name']} {rarity_stars(pet_type['rarity'])}。\n"
                f"本次成功率: {rate}%",
            )
        )

    await capture_cmd.finish(
        reply_message(event, f"{pet_type['name']} 躲开了，这次没抓到。\n本次成功率: {rate}%")
    )


boss_attack_cmd = on_command("讨伐", priority=4, block=True)


@boss_attack_cmd.handle()
async def handle_boss_attack(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    if not isinstance(event, GroupMessageEvent):
        await boss_attack_cmd.finish(reply_message(event, "公屏 Boss 只会出现在群聊里。"))

    ensure_default_broadcast_for_event(event)
    boss = active_group_bosses.get(int(event.group_id))
    if boss is None or datetime.now() >= boss["expires_at"]:
        active_group_bosses.pop(int(event.group_id), None)
        await boss_attack_cmd.finish(reply_message(event, "当前群里没有可讨伐的 Boss。"))

    pet = ensure_current_pet(event.user_id)
    damage = random.randint(
        max(1, pet_attack_power(pet) - 8),
        pet_attack_power(pet) + 12,
    )
    if random.randint(1, 100) <= 10:
        damage *= 2
        crit_text = "暴击！"
    else:
        crit_text = ""

    boss["hp"] = max(0, int(boss["hp"]) - damage)
    participants = boss["participants"]
    damage_board = boss["damage"]
    participants.add(int(event.user_id))
    damage_board[int(event.user_id)] = int(damage_board.get(int(event.user_id), 0)) + damage

    if int(boss["hp"]) <= 0:
        active_group_bosses.pop(int(event.group_id), None)
        reward_text = build_boss_reward_text(participants)
        await boss_attack_cmd.finish(
            reply_message(
                event,
                f"{pet['name']} {crit_text}造成 {damage} 点伤害，{boss['name']} 倒下了！\n{reward_text}",
            )
        )

    await boss_attack_cmd.finish(
        reply_message(
            event,
            f"{pet['name']} {crit_text}造成 {damage} 点伤害。\n"
            f"{boss['name']} 剩余血量: {boss['hp']}/{boss['max_hp']}",
        )
    )


battle_challenge_cmd = on_command("发起对战", priority=4, block=True)
battle_accept_cmd = on_command("接受挑战", priority=4, block=True)


@battle_challenge_cmd.handle()
async def handle_battle_challenge(event: MessageEvent, args: Message = CommandArg()):
    if should_ignore_group_message(event):
        return
    if not isinstance(event, GroupMessageEvent):
        await battle_challenge_cmd.finish(reply_message(event, "宠物对战只能在群聊中发起。"))

    now = datetime.now()
    last_challenge_at = get_last_battle_challenge_at(event.user_id)
    if last_challenge_at:
        last_challenge = datetime.fromisoformat(last_challenge_at)
        next_challenge = last_challenge + BATTLE_CHALLENGE_COOLDOWN
        if now < next_challenge:
            minutes = max(1, int((next_challenge - now).total_seconds() // 60) + 1)
            await battle_challenge_cmd.finish(
                reply_message(event, f"发起对战还在冷却中，请约 {minutes} 分钟后再试。")
            )

    target_id = None
    self_id = int(event.self_id)
    for segment in args:
        if segment.type != "at":
            continue
        qq = segment.data.get("qq")
        if qq and str(qq).isdigit():
            candidate = int(qq)
            if candidate not in (int(event.user_id), self_id):
                target_id = candidate
                break

    if target_id is None:
        await battle_challenge_cmd.finish(reply_message(event, "用法: @我 /发起对战 @对方"))
    if target_id == int(event.user_id):
        await battle_challenge_cmd.finish(reply_message(event, "不能自己对自己发起对战。"))
    if int(event.group_id) in pending_battles:
        await battle_challenge_cmd.finish(reply_message(event, "当前群里已经有一个待接受的挑战了。"))

    ensure_current_pet(event.user_id)
    ensure_current_pet(target_id)
    set_last_battle_challenge_at(event.user_id, now.isoformat(timespec="seconds"))
    pending_battles[int(event.group_id)] = {
        "challenger_id": int(event.user_id),
        "defender_id": target_id,
        "expires_at": datetime.now() + timedelta(minutes=BATTLE_CHALLENGE_EXPIRE_MINUTES),
    }
    await battle_challenge_cmd.finish(
        reply_message(event, "挑战已发起，等待 ")
        + MessageSegment.at(target_id)
        + Message(f" 在 {BATTLE_CHALLENGE_EXPIRE_MINUTES} 分钟内 @我并发送 /接受挑战。")
    )


@battle_accept_cmd.handle()
async def handle_battle_accept(event: MessageEvent):
    if should_ignore_group_message(event):
        return
    if not isinstance(event, GroupMessageEvent):
        await battle_accept_cmd.finish(reply_message(event, "宠物对战只能在群聊中进行。"))

    challenge = pending_battles.get(int(event.group_id))
    if challenge is None or datetime.now() >= challenge["expires_at"]:
        pending_battles.pop(int(event.group_id), None)
        await battle_accept_cmd.finish(reply_message(event, "当前没有待接受的挑战。"))
    if int(event.user_id) != int(challenge["defender_id"]):
        await battle_accept_cmd.finish(reply_message(event, "只有被挑战的用户可以接受这场对战。"))

    pending_battles.pop(int(event.group_id), None)
    challenger_id = int(challenge["challenger_id"])
    defender_id = int(challenge["defender_id"])
    winner_id, logs = simulate_pet_battle(challenger_id, defender_id)
    loser_id = defender_id if winner_id == challenger_id else challenger_id
    winner_pet, winner_leveled = add_pet_reward(winner_id, BATTLE_REWARD_EXP, BATTLE_WIN_AFFECTION)
    loser_pet = add_pet_affection(loser_id, BATTLE_LOSE_AFFECTION)

    level_text = f"，升级 {winner_leveled} 级" if winner_leveled > 0 else ""
    await battle_accept_cmd.finish(
        reply_message(
            event,
            "\n".join(logs)
            + "\n"
            + f"胜者: {winner_id} 的 {winner_pet['name']}，获得 {BATTLE_REWARD_EXP} 经验"
            + f"和 {BATTLE_WIN_AFFECTION} 好感度{level_text}。\n"
            + f"败者: {loser_id} 的 {loser_pet['name']} 失去 {abs(BATTLE_LOSE_AFFECTION)} 好感度。",
        )
    )


enable_broadcast_cmd = on_command("开启播报", priority=4, block=True)
disable_broadcast_cmd = on_command("关闭播报", priority=4, block=True)


@enable_broadcast_cmd.handle()
async def handle_enable_broadcast(event: MessageEvent):
    if should_ignore_group_message(event):
        return

    target_type, target_id, _ = context_from_event(event)
    set_broadcast_enabled(target_type, target_id, True)
    await enable_broadcast_cmd.finish(reply_message(event, "已开启野生宠物播报。"))


@disable_broadcast_cmd.handle()
async def handle_disable_broadcast(event: MessageEvent):
    if should_ignore_group_message(event):
        return

    target_type, target_id, _ = context_from_event(event)
    set_broadcast_enabled(target_type, target_id, False)
    await disable_broadcast_cmd.finish(reply_message(event, "已关闭野生宠物播报。"))
