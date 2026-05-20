from .state import recently_added_friends, chat_history, MAX_HISTORY_TURNS
from dotenv import load_dotenv
load_dotenv(".env.prod")
import os
from openai import OpenAI
from nonebot import on_message, on_command
from nonebot.adapters.onebot.v11 import MessageEvent, PrivateMessageEvent, Message
from nonebot.params import CommandArg
from .database import add_chat_messages, load_recent_chat_history
from .message_utils import plain_text_without_bot_at, reply_message, should_ignore_group_message

client = OpenAI(
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

@menu_cmd.handle()
async def handle_menu(event: PrivateMessageEvent):
    menu_text = """指令菜单

💬 聊天
  直接发消息就能和我聊天~

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
  /我的宠物              (查看/初次领取宠物)
  /查看仓库              (查看已拥有的宠物)
  /切换宠物 <宠物id>     (切换当前携带宠物)
  /打卡                  (每日一次,增加经验)
  /玩耍                  (每小时一次,额外经验)
  /互动                  (与高好感度宠物互动)
  /捕捉                  (捕捉播报出现的野生宠物)
  /讨伐                  (参与群聊公屏Boss)
  /发起对战 @用户        (发起宠物对战)
  /接受挑战              (接受别人发起的宠物对战)
  /开启播报 /关闭播报   (控制野生宠物播报)
"""
    await menu_cmd.finish(menu_text)


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

    history = chat_history.setdefault(
        user_id,
        load_recent_chat_history(user_id, MAX_HISTORY_TURNS * 2),
    )

    # 拼接 messages: system + 历史 + 本次用户消息
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_msg})

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            max_tokens=500,
        )
        reply = response.choices[0].message.content
        print(f"[DEBUG] AI 回复: {reply}")
        
        # 把这一轮加入历史
        history.append({"role": "user", "content": user_msg})
        history.append({"role": "assistant", "content": reply})
        add_chat_messages(
            user_id,
            [
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": reply},
            ],
        )
        
        # 限制历史长度: 保留最近 MAX_HISTORY_TURNS 轮(每轮 2 条)
        if len(history) > MAX_HISTORY_TURNS * 2:
            # 删掉最旧的两条(一轮)
            del history[0:2]
        
        await chat.send(reply_message(event, reply))
        
    except Exception as e:
        print(f"[DEBUG] 出错了: {type(e).__name__}: {e}")
        await chat.send(reply_message(event, f"bot出错了 ＞＜:{type(e).__name__}"))
