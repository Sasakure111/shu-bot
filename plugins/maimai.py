import math
import os
from pathlib import Path
import aiohttp
from dotenv import load_dotenv
from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, Message
from nonebot.params import CommandArg
from .message_utils import reply_message, should_ignore_group_message

load_dotenv(Path(__file__).resolve().parents[1] / ".env.prod")

# ===== Rating 计算 =====
def compute_ra(ds: float, achievement: float) -> int:
    if achievement < 50:
        base = 7.0
    elif achievement < 60:
        base = 8.0
    elif achievement < 70:
        base = 9.6
    elif achievement < 75:
        base = 11.2
    elif achievement < 80:
        base = 12.0
    elif achievement < 90:
        base = 13.6
    elif achievement < 94:
        base = 15.2
    elif achievement < 97:
        base = 16.8
    elif achievement < 98:
        base = 20.0
    elif achievement < 99:
        base = 20.3
    elif achievement < 99.5:
        base = 20.8
    elif achievement < 100:
        base = 21.1
    elif achievement < 100.5:
        base = 21.6
    else:
        base = 22.4
    return math.floor(ds * (min(100.5, achievement) / 100) * base)

# ===== 难度 / 评级映射 =====
DIFFS = ['Basic', 'Advanced', 'Expert', 'Master', 'Re:Master']
RANKS = ['D','C','B','BB','BBB','A','AA','AAA','S','S+','SS','SS+','SSS','SSS+']
RATE_MAP = ['d','c','b','bb','bbb','a','aa','aaa','s','sp','ss','ssp','sss','sssp']

def fmt_rank(rate_str: str) -> str:
    try:
        return RANKS[RATE_MAP.index(rate_str)]
    except ValueError:
        return rate_str

# ===== 查询 diving-fish =====
async def fetch_b50(username: str, token: str):
    headers = {"Developer-Token": token}
    payload = {"username": username, "b50": True}
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://www.diving-fish.com/api/maimaidxprober/query/player",
            json=payload,
            headers=headers
        ) as resp:
            if resp.status == 400:
                return None, "用户不存在或未开启第三方查询"
            if resp.status == 403:
                return None, "没有查询权限，请检查 token"
            return await resp.json(), None

# ===== 格式化输出 =====
def format_b50(data: dict) -> str:
    nickname = data.get("nickname", "unknown")
    charts = data.get("charts", {})
    sd_list = charts.get("sd", [])
    dx_list = charts.get("dx", [])

    # 排序取 best
    def ra_of(c):
        return compute_ra(c["ds"], c["achievements"])

    sd_best = sorted(sd_list, key=ra_of, reverse=True)[:35]
    dx_best = sorted(dx_list, key=ra_of, reverse=True)[:15]

    sd_total = sum(ra_of(c) for c in sd_best)
    dx_total = sum(ra_of(c) for c in dx_best)
    total = sd_total + dx_total

    lines = [
        f"🎵 {nickname} 的 B50",
        f"Rating: {total}  (SD {sd_total} + DX {dx_total})",
        "",
        "── SD Best 35 ──",
    ]
    for i, c in enumerate(sd_best, 1):
        ra = ra_of(c)
        diff = DIFFS[c['level_index']]
        rank = fmt_rank(c['rate'])
        lines.append(f"#{i:02d} {c['title'][:16]} [{diff}] {c['ds']} | {rank} {c['achievements']:.1f}% | Ra:{ra}")

    lines += ["", "── DX Best 15 ──"]
    for i, c in enumerate(dx_best, 1):
        ra = ra_of(c)
        diff = DIFFS[c['level_index']]
        rank = fmt_rank(c['rate'])
        lines.append(f"#{i:02d} {c['title'][:16]} [{diff}] {c['ds']} | {rank} {c['achievements']:.1f}% | Ra:{ra}")

    return "\n".join(lines)

# ===== NoneBot 指令 =====
DIVING_FISH_TOKEN = os.getenv("DIVING_FISH_TOKEN", "")

b50_cmd = on_command("b50", priority=5, block=True)

@b50_cmd.handle()
async def handle_b50(event: MessageEvent, args: Message = CommandArg()):
    if should_ignore_group_message(event):
        return

    username = args.extract_plain_text().strip()
    if not username:
        await b50_cmd.finish(reply_message(event, "用法：/b50 <水鱼用户名>"))
    if not DIVING_FISH_TOKEN:
        await b50_cmd.finish(reply_message(event, "token 未配置，请联系管理员"))
    
    await b50_cmd.send(reply_message(event, "查询中，请稍等..."))
    data, err = await fetch_b50(username, DIVING_FISH_TOKEN)
    if err:
        await b50_cmd.finish(reply_message(event, f"查询失败：{err}"))
    
    await b50_cmd.finish(reply_message(event, format_b50(data)))
