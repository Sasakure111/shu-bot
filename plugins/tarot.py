import random
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import PrivateMessageEvent, Message
from nonebot.params import CommandArg
import os

from .database import add_chat_messages, load_recent_chat_history
from .state import MAX_HISTORY_TURNS, chat_history, recently_added_friends

load_dotenv(Path(__file__).resolve().parents[1] / ".env.prod")

# 复用 echo.py 里的 OpenAI 客户端
# 如果你 echo.py 里 client 是模块级变量,直接 import 过来
#from .echo import client

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL"),
)


# ===== 22 张大阿尔卡那牌库 =====
TAROT_DECK = [
    {"name": "愚者 The Fool", "upright": "新的开始、冒险、自由、纯真", "reversed": "鲁莽、犹豫、错误的开始"},
    {"name": "魔术师 The Magician", "upright": "创造力、行动力、技能、自信", "reversed": "欺骗、能力不足、犹豫不决"},
    {"name": "女祭司 The High Priestess", "upright": "直觉、神秘、潜意识、内在智慧", "reversed": "秘密、压抑、忽视直觉"},
    {"name": "皇后 The Empress", "upright": "丰饶、母性、创造、自然", "reversed": "依赖、空虚、创造力受阻"},
    {"name": "皇帝 The Emperor", "upright": "权威、稳定、结构、控制", "reversed": "专制、僵化、滥用权力"},
    {"name": "教皇 The Hierophant", "upright": "传统、教导、信仰、规范", "reversed": "叛逆、个人主义、打破常规"},
    {"name": "恋人 The Lovers", "upright": "爱、和谐、选择、结合", "reversed": "失衡、错误选择、关系破裂"},
    {"name": "战车 The Chariot", "upright": "胜利、决心、控制、前进", "reversed": "失控、缺乏方向、阻力"},
    {"name": "力量 Strength", "upright": "勇气、耐心、内在力量、温柔的控制", "reversed": "自我怀疑、软弱、失控"},
    {"name": "隐者 The Hermit", "upright": "内省、独处、智慧、寻找答案", "reversed": "孤立、固执、拒绝帮助"},
    {"name": "命运之轮 Wheel of Fortune", "upright": "转机、命运、循环、好运", "reversed": "厄运、停滞、抗拒变化"},
    {"name": "正义 Justice", "upright": "公正、真相、平衡、责任", "reversed": "不公、偏见、逃避责任"},
    {"name": "倒吊人 The Hanged Man", "upright": "牺牲、新视角、暂停、放下", "reversed": "拖延、抗拒、无谓牺牲"},
    {"name": "死神 Death", "upright": "结束、转变、重生、放下过去", "reversed": "停滞、抗拒改变、害怕结束"},
    {"name": "节制 Temperance", "upright": "平衡、节制、和谐、耐心", "reversed": "失衡、过度、冲突"},
    {"name": "恶魔 The Devil", "upright": "诱惑、束缚、物质欲望、阴影", "reversed": "解脱、觉醒、打破束缚"},
    {"name": "塔 The Tower", "upright": "突变、崩塌、觉醒、揭露真相", "reversed": "避免灾难、缓慢的改变、内在崩塌"},
    {"name": "星星 The Star", "upright": "希望、灵感、宁静、新的可能", "reversed": "失望、悲观、失去信心"},
    {"name": "月亮 The Moon", "upright": "幻觉、潜意识、不安、直觉", "reversed": "迷雾散去、揭露真相、释放恐惧"},
    {"name": "太阳 The Sun", "upright": "成功、喜悦、活力、清晰", "reversed": "暂时的挫折、过度乐观、迷失方向"},
    {"name": "审判 Judgement", "upright": "重生、觉醒、宽恕、召唤", "reversed": "自我怀疑、拒绝改变、悔恨"},
    {"name": "世界 The World", "upright": "完成、成就、整合、圆满", "reversed": "未完成、停滞、缺乏整合"},
]


# ===== 用户状态: 记录谁正在算塔罗 =====
# {user_id: True} 表示这个用户已经发了 /塔罗,正在等待输入问题
waiting_for_question = {}


async def is_waiting_for_tarot_question(event: PrivateMessageEvent) -> bool:
    return event.user_id in waiting_for_question


# ===== /塔罗 命令: 进入算塔罗状态 =====
tarot_start = on_command("塔罗", aliases={"抽塔罗", "占卜"}, priority=1, block=True)

@tarot_start.handle()
async def handle_tarot_start(event: PrivateMessageEvent):
    user_id = event.user_id
    waiting_for_question[user_id] = True
    
    await tarot_start.send(
        "🔮 水晶球已就位\n"
        "想问什么呢? 直接告诉我你的困扰 ⌓‿⌓\n"
        "(回复 取消 可以退出)"
    )


# ===== 监听等待状态的用户输入 =====
# priority 比 echo.py 的 chat 高,确保先被这里处理
tarot_question = on_message(
    rule=is_waiting_for_tarot_question,
    priority=8,
    block=True,
)

@tarot_question.handle()
async def handle_tarot_question(event: PrivateMessageEvent):
    user_id = event.user_id
    
    # 如果不是"等待输入问题"状态,直接放行给 echo.py 处理
    if user_id not in waiting_for_question:
        return
    
    # 如果是刚加的好友,跳过
    if user_id in recently_added_friends:
        return
    
    question = event.get_plaintext().strip()
    
    # 处理取消
    if question in ["取消", "cancel", "退出"]:
        del waiting_for_question[user_id]
        await tarot_question.send("好~水晶球收起来了 ⌓‿⌓")
        return
    
    if not question:
        return
    
    # 清除等待状态
    del waiting_for_question[user_id]
    
    # 抽牌 (随机选一张 + 60% 正位 / 40% 逆位)
    card = random.choice(TAROT_DECK)
    is_upright = random.random() < 0.6
    position = "正位" if is_upright else "逆位"
    meaning = card["upright"] if is_upright else card["reversed"]
    
    print(f"[DEBUG] 用户 {user_id} 塔罗占卜: 问题={question}, 牌={card['name']} {position}")
    
    # 调用 AI 生成解读
    tarot_prompt = f"""你是一位神秘但温柔的塔罗占卜师「OW」,现在要为来访者解读塔罗牌。

来访者的问题: {question}

抽到的牌: {card['name']} - {position}
牌面关键词: {meaning}

请按以下格式输出解读(不要超过 200 字):

🎴 抽到了「{card['name']}」- {position}

【牌面】(用一两句话描述这张牌的画面/象征)

【OW的解读】(结合来访者的问题,给出温柔但有深度的解读。可以指出当下状态、给点小建议。语气可以稍微神秘但不要装神弄鬼)

注意:
- 不要给极端的预言(比如"你一定会..."、"绝对不要...")
- 保持开放性,留给来访者自己思考的空间
- 偶尔可以用一两个颜文字,但不要过度
- 不要过度承诺好结果或恐吓坏结果"""

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一位塔罗占卜师,擅长结合具体问题给出有启发性的解读。"},
                {"role": "user", "content": tarot_prompt},
            ],
            max_tokens=400,
        )
        reply = response.choices[0].message.content
        
        # 在解读后追加免责声明
        full_reply = reply + "\n\n———\n💫 塔罗只是娱乐和自我反思的小工具,认真你就输啦 ⌓‿⌓ 真正的答案在你自己心里！"
        
        user_history_message = {
            "role": "user",
            "content": f"塔罗提问: {question}\n抽到的牌: {card['name']} - {position}\n牌面关键词: {meaning}",
        }
        assistant_history_message = {"role": "assistant", "content": full_reply}

        history = chat_history.setdefault(
            user_id,
            load_recent_chat_history(user_id, MAX_HISTORY_TURNS * 2),
        )
        history.append(user_history_message)
        history.append(assistant_history_message)
        add_chat_messages(user_id, [user_history_message, assistant_history_message])

        if len(history) > MAX_HISTORY_TURNS * 2:
            del history[0:2]

        await tarot_question.send(full_reply)
        
    except Exception as e:
        print(f"[DEBUG] 塔罗 AI 调用失败: {type(e).__name__}: {e}")
        await tarot_question.send(f"水晶球出问题了 ＞＜: {type(e).__name__}")
