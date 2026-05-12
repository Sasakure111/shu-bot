import re
from datetime import datetime, timedelta

from nonebot import on_command, require
from nonebot.adapters.onebot.v11 import Bot, PrivateMessageEvent
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11 import Message

from nonebot import require
require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

# 必须先 require,然后才能 import


# ===== 提醒数据存储 =====
# {user_id: [{"id": 1, "time": datetime, "content": "xxx", "job_id": "xxx"}, ...]}
user_reminders = {}

# 全局自增 ID,用来给每条提醒一个编号
next_reminder_id = 1


# ===== 时间解析函数 =====
def parse_time(time_str: str) -> datetime | None:
    """
    支持三种格式:
    - HH:MM     (如 18:00, 9:30)
    - X分钟后   (如 30分钟后, 5分钟后)
    - X小时后   (如 1小时后, 2小时后)
    返回目标 datetime,失败返回 None
    """
    now = datetime.now()
    
    # 格式 1: HH:MM
    match = re.match(r'^(\d{1,2}):(\d{2})$', time_str)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        if not (0 <= hour < 24 and 0 <= minute < 60):
            return None
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        # 如果目标时间已过,定到明天同时间
        if target <= now:
            target += timedelta(days=1)
        return target
    
    # 格式 2: X分钟后
    match = re.match(r'^(\d+)分钟?后$', time_str)
    if match:
        minutes = int(match.group(1))
        return now + timedelta(minutes=minutes)
    
    # 格式 3: X小时后
    match = re.match(r'^(\d+)(?:个)?小时后$', time_str)
    if match:
        hours = int(match.group(1))
        return now + timedelta(hours=hours)
    
    return None


# ===== /提醒 命令 =====
remind_cmd = on_command("提醒", priority=1, block=True)

@remind_cmd.handle()
async def handle_remind(bot: Bot, event: PrivateMessageEvent, args: Message = CommandArg()):
    global next_reminder_id
    
    user_id = event.user_id
    arg_text = args.extract_plain_text().strip()
    
    if not arg_text:
        await remind_cmd.send(
            "用法: /提醒 <时间> <内容>\n"
            "支持的时间格式:\n"
            "• HH:MM (如 18:00)\n"
            "• X分钟后 (如 30分钟后)\n"
            "• X小时后 (如 2小时后)\n"
            "\n"
            "例子:\n"
            "/提醒 18:00 解锁U校园\n"
            "/提醒 30分钟后 喝水\n"
            "/提醒 2小时后 该睡觉啦"
        )
        return
    
    # 拆分时间和内容: 第一个空格之前是时间,之后是内容
    parts = arg_text.split(maxsplit=1)
    if len(parts) < 2:
        await remind_cmd.send("提醒内容不能为空哦 ＞＜")
        return
    
    time_str, content = parts[0], parts[1]
    target_time = parse_time(time_str)
    
    if target_time is None:
        await remind_cmd.send(
            f"看不懂 '{time_str}' 这个时间格式 ＞＜\n"
            "试试: 18:00 / 30分钟后 / 2小时后"
        )
        return
    
    # 创建提醒
    reminder_id = next_reminder_id
    next_reminder_id += 1
    
    job_id = f"reminder_{user_id}_{reminder_id}"
    
    # 注册定时任务
    scheduler.add_job(
        send_reminder,
        "date",
        run_date=target_time,
        args=[bot, user_id, reminder_id, content],
        id=job_id,
    )
    
    # 存到字典
    user_reminders.setdefault(user_id, []).append({
        "id": reminder_id,
        "time": target_time,
        "content": content,
        "job_id": job_id,
    })
    
    time_display = target_time.strftime("%m月%d日 %H:%M")
    await remind_cmd.send(
        f"⏰ 提醒已设置 #{reminder_id}\n"
        f"时间: {time_display}\n"
        f"内容: {content}"
    )
    print(f"[DEBUG] 已为 {user_id} 设置提醒 #{reminder_id}: {target_time} - {content}")


# ===== 触发提醒时调用的函数 =====
async def send_reminder(bot: Bot, user_id: int, reminder_id: int, content: str):
    try:
        await bot.send_private_msg(
            user_id=user_id,
            message=f"⏰ 提醒到啦~\n{content} ⌓‿⌓"
        )
        print(f"[DEBUG] 已发送提醒 #{reminder_id} 给 {user_id}")
    except Exception as e:
        print(f"[DEBUG] 发送提醒失败: {type(e).__name__}: {e}")
    
    # 从用户提醒列表中移除已触发的提醒
    if user_id in user_reminders:
        user_reminders[user_id] = [
            r for r in user_reminders[user_id] if r["id"] != reminder_id
        ]


# ===== /我的提醒 =====
list_cmd = on_command("我的提醒", aliases={"提醒列表"}, priority=1, block=True)

@list_cmd.handle()
async def handle_list(event: PrivateMessageEvent):
    user_id = event.user_id
    reminders = user_reminders.get(user_id, [])
    
    if not reminders:
        await list_cmd.send("你还没有任何提醒呢 ⌓‿⌓")
        return
    
    # 按时间排序
    sorted_reminders = sorted(reminders, key=lambda r: r["time"])
    
    lines = ["📋 你的提醒列表:"]
    for r in sorted_reminders:
        time_display = r["time"].strftime("%m月%d日 %H:%M")
        lines.append(f"#{r['id']} | {time_display} | {r['content']}")
    
    lines.append("\n用 /取消提醒 <编号> 可以删除")
    await list_cmd.send("\n".join(lines))


# ===== /取消提醒 =====
cancel_cmd = on_command("取消提醒", priority=1, block=True)

@cancel_cmd.handle()
async def handle_cancel(event: PrivateMessageEvent, args: Message = CommandArg()):
    user_id = event.user_id
    arg_text = args.extract_plain_text().strip()
    
    if not arg_text:
        await cancel_cmd.send("用法: /取消提醒 <编号>\n用 /我的提醒 查看编号")
        return
    
    try:
        target_id = int(arg_text)
    except ValueError:
        await cancel_cmd.send("编号要是数字哦 ＞＜")
        return
    
    reminders = user_reminders.get(user_id, [])
    target = next((r for r in reminders if r["id"] == target_id), None)
    
    if target is None:
        await cancel_cmd.send(f"找不到 #{target_id} 这条提醒")
        return
    
    # 取消定时任务
    try:
        scheduler.remove_job(target["job_id"])
    except Exception as e:
        print(f"[DEBUG] 取消定时任务失败 (可能已触发): {e}")
    
    # 从列表移除
    user_reminders[user_id] = [r for r in reminders if r["id"] != target_id]
    
    await cancel_cmd.send(f"已取消提醒 #{target_id}: {target['content']} ⌓‿⌓")