import random

from datetime import date
from nonebot import on_command
from nonebot.adapters.onebot.v11 import PrivateMessageEvent

fortune_cmd = on_command("今日运势", aliases={"运势", "运气"}, priority=5, block=True)

# 运势等级

# 各方面运势文案
FORTUNES = {
    "学业": [
        "今天的代码一次编译通过，绩点保佑",
        "高数题目看三遍才能读懂题意，建议放弃治疗",
        "今天适合死磕一道题，会有顿悟时刻",
        "课堂摸鱼被点名，请正襟危坐",
        "复习效率满格，把昨天摸的鱼还回去",
        "今天写作业脑子转得飞快，趁热打铁",
        "建议今天不要开 VSCode，否则停不下来",
    ],
    "音游": [
        "手感在线，今天冲分好时机",
        "AP 就差一个 note，下次一定",
        "建议选简单曲目热手，不然翻车概率 ?%",
        "今天机厅人少，场地全是你的",
        "手汗来袭，接触面告急",
        "今天随机选曲，说不定解锁新曲风",
        "今日必吃分，上大分！",
    ],
    "社交": [
        "今天适合找朋友拼机，气氛会很好",
        "少说多听，你懂的",
        "今天发消息都会秒回，勇敢出击",
        "独处充电日，不想理人是正常的",
        "群消息设免打扰，世界清净了",
        "今天适合夸一夸身边的人",
        "有人找你倾诉，请备好耳朵",
    ],
    "饮食": [
        "今天的KFC双倍治愈",
        "奶茶请选低咖啡因，你知道为什么",
        "食堂的菜今天意外地好吃",
        "建议补充红肉，铁元素在呼唤你",
        "今天适合喝热水，真的",
        "晚饭早点吃，别等到九点",
        "水果补一补，VC 不够用了",
    ],
}

# 幸运物
LUCKY_ITEMS = [
    "刷AP/FC", "奶茶", "大口吃炸鸡", "一杯纯牛奶",
    "奖励自己", "学习", "出勤", "听音游曲",
    "画画", "运动",
]

# 忌
BAD_ITEMS = [
    "奶茶", "熬夜", "饿肚子",
    "在群里发电", "手机没电", "课上开小差",
    "开新坑", "长时间刷手机",
]

@fortune_cmd.handle()
async def handle_fortune(event: PrivateMessageEvent):
    # 用日期+用户id做种，同一天结果一致
    seed = int(str(date.today()).replace("-", "")) + event.user_id
    rng = random.Random(seed)

    score = rng.randint(0, 100)

    if score < 10:
        level = "大凶"
    elif score < 20:
        level = "凶"
    elif score < 30:
        level = "末凶"
    elif score < 40:
        level = "小凶"
    elif score < 50:
        level = "平"
    elif score < 60:
        level = "小吉"
    elif score < 70:
        level = "末吉"
    elif score < 80:
        level = "吉"
    elif score < 90:
        level = "中吉"
    else:
        level = "大吉"
    lucky = rng.choice(LUCKY_ITEMS)
    bad = rng.choice(BAD_ITEMS)

    # 随机抽3个方面
    aspects = rng.sample(list(FORTUNES.keys()), 3)
    aspect_lines = "\n".join(
        f"  {a}：{rng.choice(FORTUNES[a])}" for a in aspects
    )

    msg = f"""· 今日运势

✦ 总运：{level}（{score}分）

{aspect_lines}

🍀 宜：{lucky}
🚫 忌：{bad}

——OW掐指一算，今日卦象已定"""

    await fortune_cmd.finish(msg)