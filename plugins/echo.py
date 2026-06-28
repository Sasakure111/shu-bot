from .state import recently_added_friends, chat_history, MAX_HISTORY_TURNS
from dotenv import load_dotenv
load_dotenv(".env.prod")
import asyncio
import os
import re
from openai import AsyncOpenAI
from nonebot import on_message, on_command
from nonebot.matcher import Matcher
from nonebot.adapters.onebot.v11 import MessageEvent, PrivateMessageEvent, Message
from nonebot.params import CommandArg
from .database import (
    add_chat_messages,
    clear_chat_history,
    get_user_chat_mode,
    load_recent_chat_history,
    set_user_chat_mode,
)
from .message_utils import plain_text_without_bot_at, reply_message, should_ignore_group_message

CHAT_MODE_CASUAL = "casual"
CHAT_MODE_DEEP = "deep"
CASUAL_REPLY_DELAY_SECONDS = 0.5
chat_modes = {}
pending_clear_memory_users = set()

CASUAL_PROMPT = """
当前聊天模式：闲聊模式。
请严格遵守 persona 中的闲聊模式规则。
"""

DEEP_PROMPT = """
当前处于深聊模式。
请严格遵守 persona 中的深聊模式规则。
"""

client = AsyncOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL"),
)


# 从config读取人设
_persona_path = os.path.join(os.path.dirname(__file__), "..", "config", "persona.txt")
_persona_example_path = os.path.join(os.path.dirname(__file__), "..", "config", "persona.example.txt")

if os.path.exists(_persona_path):
    with open(_persona_path, "r", encoding="utf-8") as f:
        SYSTEM_PROMPT = f.read()
else:
    # persona.txt 不存在时,回退到示例配置
    with open(_persona_example_path, "r", encoding="utf-8") as f:
        SYSTEM_PROMPT = f.read()
    print("[WARNING] config/persona.txt 不存在,使用示例配置。请创建 persona.txt 并填写你的人设。")


menu_cmd = on_command("菜单", priority=1, block=True)
casual_cmd = on_command("闲聊", priority=1, block=True)
deep_cmd = on_command("深聊", priority=1, block=True)
clear_memory_cmd = on_command("清空记忆", priority=1, block=True)
# 注意：/是 /否 是通用确认词，RPG 等其他插件（priority=4）也在用。
# 这里改成 block=False，只有「确实有待确认的清空记忆操作」时才 stop_propagation 吃掉事件；
# 否则静默放行，交给后面的插件处理（修掉 /转生 等二级确认被这里拦截的 bug）。
confirm_clear_memory_cmd = on_command("是", priority=1, block=False)
cancel_clear_memory_cmd = on_command("否", priority=1, block=False)

@menu_cmd.handle()
async def handle_menu(event: MessageEvent):
    menu_text = """指令菜单

💬 聊天
  直接发消息就能和我聊天~
  /闲聊 — 简短回复,可能拆成几条消息
  /深聊 — 认真回复,一次只发一条消息
  /清空记忆 — 清空你的聊天上下文

🎴 塔罗
  /塔罗 — 抽一张塔罗牌

🔮 运势
  /今日运势 — 查看今日运势（每天结果固定）

⏰ 提醒
  /提醒 08:30 起床      (指定时间)
  /提醒 30分钟后 喝水   (相对时间)
  /提醒 2小时后 开会
  /我的提醒             (查看提醒)
  /取消提醒 1           (取消第1个)

🎵 maimai
  /b50 <水鱼用户名>     (查询B50)

🐾 宠物
  /宠物                (查看宠物功能菜单)

⚔️ RPG游戏
  /冒险                (进入RPG冒险)
  /玩家                (查看局外玩家信息)
"""
    await menu_cmd.finish(menu_text)


@casual_cmd.handle()
async def handle_casual_mode(event: MessageEvent):
    chat_modes[event.user_id] = CHAT_MODE_CASUAL
    set_user_chat_mode(event.user_id, CHAT_MODE_CASUAL)
    await casual_cmd.finish(reply_message(event, "好呀\n那我说短点"))


@deep_cmd.handle()
async def handle_deep_mode(event: MessageEvent):
    chat_modes[event.user_id] = CHAT_MODE_DEEP
    set_user_chat_mode(event.user_id, CHAT_MODE_DEEP)
    await deep_cmd.finish(reply_message(event, "好\n我会认真一点回你"))


@clear_memory_cmd.handle()
async def handle_clear_memory(event: MessageEvent):
    pending_clear_memory_users.add(event.user_id)
    await clear_memory_cmd.finish(reply_message(event, "确认清空你的聊天记忆吗\n发送 /是 确认\n发送 /否 取消"))


@confirm_clear_memory_cmd.handle()
async def handle_confirm_clear_memory(matcher: Matcher, event: MessageEvent):
    user_id = event.user_id
    if user_id not in pending_clear_memory_users:
        # 不是给「清空记忆」的确认，放行给 RPG 等其他插件处理
        return

    matcher.stop_propagation()
    pending_clear_memory_users.discard(user_id)
    chat_history.pop(user_id, None)
    deleted_count = clear_chat_history(user_id)
    print(f"[DEBUG] 用户 {user_id} 清空聊天记忆,删除 {deleted_count} 条数据库记录")
    await confirm_clear_memory_cmd.finish(reply_message(event, "清空啦\n我们重新开始"))


@cancel_clear_memory_cmd.handle()
async def handle_cancel_clear_memory(matcher: Matcher, event: MessageEvent):
    user_id = event.user_id
    if user_id not in pending_clear_memory_users:
        # 不是给「清空记忆」的取消，放行给 RPG 等其他插件处理
        return

    matcher.stop_propagation()
    pending_clear_memory_users.discard(user_id)
    await cancel_clear_memory_cmd.finish(reply_message(event, "好\n那就先留着"))


def get_chat_mode(user_id: int) -> str:
    if user_id not in chat_modes:
        chat_modes[user_id] = get_user_chat_mode(user_id, CHAT_MODE_DEEP)
    return chat_modes[user_id]


def split_casual_reply(reply: str) -> list[str]:
    parts = []
    for line in reply.replace("\r\n", "\n").split("\n"):
        text = line.strip()
        if not text:
            continue
        text = text.lstrip("-*0123456789.、)）！! ")
        for segment in re.split(r"(?<=[。？?~～；;])\s*", text):
            segment = segment.strip(" ，,。？?~～；;")
            if segment:
                parts.append(segment)

    if not parts:
        stripped_reply = reply.strip()
        return [stripped_reply] if stripped_reply else []

    split_parts = []
    for part in parts:
        chunks = re.split(
            r"[，,、]\s*|(?<=[\u4e00-\u9fff）)])\s+(?=[\u4e00-\u9fff（(])",
            part,
        )
        split_parts.extend(chunk.strip() for chunk in chunks if chunk.strip())

    return split_parts


def build_assistant_memory(reply_parts: list[str]) -> str:
    return "\n".join(part.strip() for part in reply_parts if part.strip())


def build_system_prompt(chat_mode: str) -> str:
    if chat_mode == CHAT_MODE_CASUAL:
        return f"{SYSTEM_PROMPT.rstrip()}\n\n{CASUAL_PROMPT.strip()}"
    return f"{SYSTEM_PROMPT.rstrip()}\n\n{DEEP_PROMPT.strip()}"


chat = on_message(priority=10, block=True)

@chat.handle()
async def handle_chat(event: MessageEvent):
    if should_ignore_group_message(event):
        return

    user_msg = plain_text_without_bot_at(event)
    print(f"[DEBUG] 收到消息: {user_msg}")
    user_id = event.user_id
    
    if not user_msg:
        return
    
    if user_id in recently_added_friends:
        print(f"[DEBUG] 用户 {user_id} 是刚加的好友,跳过本次回复")
        return

    # 仅在内存未缓存时才查库；setdefault 会每次都先把默认值算出来，等于每条消息都查一次 DB
    if user_id not in chat_history:
        chat_history[user_id] = load_recent_chat_history(user_id, MAX_HISTORY_TURNS * 2)
    history = chat_history[user_id]

    chat_mode = get_chat_mode(user_id)
    # 拼接 messages: system + 历史 + 本次用户消息
    messages = [{"role": "system", "content": build_system_prompt(chat_mode)}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_msg})

    try:
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            max_tokens=60 if chat_mode == CHAT_MODE_CASUAL else 500,
        )
        reply = response.choices[0].message.content
        print(f"[DEBUG] AI 回复: {reply}")
        if not reply or not reply.strip():  # 内容被截断/异常返回时 content 可能为 None 或空，避免后续崩溃
            await chat.send(reply_message(event, "我刚刚走神了，再跟我说一遍呗 ⌓‿⌓"))
            return
        reply_parts = split_casual_reply(reply) if chat_mode == CHAT_MODE_CASUAL else [reply]
        memory_reply = build_assistant_memory(reply_parts)
        
        # 把这一轮加入历史
        history.append({"role": "user", "content": user_msg})
        history.append({"role": "assistant", "content": memory_reply})
        add_chat_messages(
            user_id,
            [
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": memory_reply},
            ],
        )
        
        # 限制历史长度: 保留最近 MAX_HISTORY_TURNS 轮(每轮 2 条)
        if len(history) > MAX_HISTORY_TURNS * 2:
            # 删掉最旧的两条(一轮)
            del history[0:2]
        
        for index, reply_part in enumerate(reply_parts):
            if index > 0:
                await asyncio.sleep(CASUAL_REPLY_DELAY_SECONDS)
            await chat.send(reply_message(event, reply_part))
        
    except Exception as e:
        print(f"[DEBUG] 出错了: {type(e).__name__}: {e}")
        await chat.send(reply_message(event, f"bot出错了 ＞＜:{type(e).__name__}"))
