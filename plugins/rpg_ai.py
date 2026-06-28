"""AI GM 旁白（DeepSeek）。只负责氛围描写，数值一律来自 rpg_engine。

设计原则：
- 所有调用都有超时与异常兜底，失败时返回 None，由调用方退回到固定文案，游戏永不因 AI 故障而中断。
- 旁白只写"画面/气氛/情绪"，不编造伤害、金币、掉落等数值（这些由引擎给出后再拼接）。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv(Path(__file__).resolve().parents[1] / ".env.prod")

_client = AsyncOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL"),
)

_MODEL = "deepseek-chat"
_TIMEOUT = 12.0  # 秒；超时即放弃 AI 旁白，退回固定文案

_SYSTEM = (
    "你是一位奇幻冒险跑团的游戏主持人（GM）。"
    "用第二人称『你』向冒险者讲述场景，文笔凝练、有画面感与代入感。"
    "只描写氛围、动作和情绪，绝不杜撰任何数值（HP、伤害、金币、掉落、概率都不要提）。"
    "语言为简体中文，不要使用 Markdown 标题或列表符号。"
)


async def _chat(user_prompt: str, *, max_tokens: int = 200) -> str | None:
    """调用 DeepSeek，返回旁白文本；任何异常/超时都返回 None。"""
    try:
        resp = await asyncio.wait_for(
            _client.chat.completions.create(
                model=_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=1.05,
            ),
            timeout=_TIMEOUT,
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or None
    except Exception as exc:  # 网络错误、超时、鉴权失败……一律兜底
        print(f"[rpg_ai] 旁白生成失败，已退回固定文案：{exc}")
        return None


def _dice_brief(character: dict[str, Any]) -> str:
    rs = character.get("random_stats", {})
    return f"幸运{rs.get('luck', 0)}、魅力{rs.get('charm', 0)}"


async def narrate_opening(character: dict[str, Any]) -> str | None:
    """每局冒险的开场白（作为角色背景展示）。"""
    prompt = (
        "为一局新的奇幻冒险写一段开场白。\n"
        f"冒险者职业：{character.get('class_name', '冒险者')}\n"
        f"职业印象：{character.get('description', '')}\n"
        f"气质（{_dice_brief(character)}，仅供你把握性格，不要写出数字）\n"
        "要求：80~140 字，交代他/她为何踏上旅途、眼前秘境的第一幕景象，"
        "结尾落在『第一道岔路已在脚下』的氛围上。只输出正文。"
    )
    return await _chat(prompt, max_tokens=220)


async def narrate_encounter(character: dict[str, Any], enemy: dict[str, Any]) -> str | None:
    """战斗遭遇的开场描写（敌人登场）。"""
    is_boss = enemy.get("rank") == "boss"
    prompt = (
        "为一场战斗写一句登场遭遇的描写。\n"
        f"冒险者职业：{character.get('class_name', '冒险者')}\n"
        f"敌人：{enemy.get('name', '敌人')}"
        f"（{'本章Boss，气势骇人' if is_boss else enemy.get('rank_name', '') + '等级的对手'}）\n"
        "要求：30~60 字，描写敌人如何出现、现场气氛与紧张感，"
        f"{'要有压迫感和史诗感' if is_boss else '简短利落'}。只输出正文，不要换行。"
    )
    return await _chat(prompt, max_tokens=120)


async def narrate_ending(character: dict[str, Any], result: str) -> str | None:
    """结局描写：victory 通关 / death 死亡 / rebirth 转生。"""
    scene = {
        "victory": "冒险者击败了最后的强敌，秘境的尽头透出光亮，他/她活着走了出来。写一段凯旋而归、余味悠长的收尾。",
        "death": "冒险者倒在了秘境深处，旅途到此为止。写一段悲壮但不失尊严的落幕，带一点宿命感。",
        "rebirth": "冒险者选择中断旅程、以转生归来。写一段告别当下、轮回再启的收束。",
    }.get(result, "为这局冒险写一段收尾。")
    prompt = (
        f"为一局冒险写结局旁白。\n"
        f"冒险者职业：{character.get('class_name', '冒险者')}\n"
        f"情境：{scene}\n"
        "要求：60~110 字，第二人称，情绪到位。只输出正文。"
    )
    return await _chat(prompt, max_tokens=200)


async def narrate_player_welcome(player_name: str, title: str, level: int, reputation: int) -> str | None:
    prompt = (
        "给RPG玩家页面写一句AI GM欢迎词。\n"
        f"玩家名：{player_name}\n"
        f"局外等级：Lv.{level}\n"
        f"声望称号：{title}，声望值：{reputation}\n"
        "要求：简体中文，像GM对冒险者说话。只输出一句话，不要引号，不要换行。"
    )
    text = await _chat(prompt, max_tokens=60)
    if text is None:
        return None
    text = " ".join(text.split())
    return text or None
