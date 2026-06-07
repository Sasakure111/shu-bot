import re
from datetime import datetime, timedelta

from nonebot import get_bot, get_driver, on_command, require
from nonebot.adapters.onebot.v11 import Bot, PrivateMessageEvent
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11 import Message

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

# 必须先 require,然后才能 import

from .database import (
    add_reminder,
    delete_reminder,
    get_reminder,
    list_all_reminders,
    list_user_reminders,
)

# ===== 提醒数据存储 =====
# 提醒持久化在 SQLite (database.py 的 reminders 表),重启不丢。
# APScheduler 只负责"到点触发",任务在 send_reminder 里用 get_bot() 现取 Bot,
# 因此不会把不可 pickle 的 Bot 塞进任务参数,触发后从数据库删除。


def _job_id(reminder_id: int) -> str:
    return f"reminder_{reminder_id}"


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


def schedule_reminder_job(reminder_id: int, user_id: int, target_time: datetime) -> None:
    """注册(或覆盖)一条提醒的定时任务。"""
    scheduler.add_job(
        send_reminder,
        "date",
        run_date=target_time,
        args=[reminder_id],
        id=_job_id(reminder_id),
        replace_existing=True,
        misfire_grace_time=None,  # 错过也补发,避免重启窗口内的提醒被丢弃
    )


# ===== /提醒 命令 =====
remind_cmd = on_command("提醒", priority=1, block=True)

@remind_cmd.handle()
async def handle_remind(event: PrivateMessageEvent, args: Message = CommandArg()):
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

    # 先落库,拿到持久化的提醒 ID
    reminder_id = add_reminder(user_id, target_time.isoformat(), content)

    # 再注册定时任务(任务触发时按 ID 现取数据)
    schedule_reminder_job(reminder_id, user_id, target_time)

    time_display = target_time.strftime("%m月%d日 %H:%M")
    await remind_cmd.send(
        f"⏰ 提醒已设置 #{reminder_id}\n"
        f"时间: {time_display}\n"
        f"内容: {content}"
    )
    print(f"[DEBUG] 已为 {user_id} 设置提醒 #{reminder_id}: {target_time} - {content}")


# 发送失败时的重试间隔(Bot 掉线等情况),避免提醒被直接丢弃
SEND_RETRY_SECONDS = 60


# ===== 触发提醒时调用的函数 =====
async def send_reminder(reminder_id: int):
    reminder = get_reminder(reminder_id)
    if reminder is None:
        # 已被取消或已处理
        return

    user_id = int(reminder["user_id"])
    content = reminder["content"]
    try:
        bot: Bot = get_bot()
        await bot.send_private_msg(
            user_id=user_id,
            message=f"⏰ 提醒到啦~\n{content} ⌓‿⌓"
        )
    except Exception as e:
        # Bot 没连上或发送失败:不删库,过一会儿重试,避免提醒丢失
        print(f"[DEBUG] 发送提醒 #{reminder_id} 失败,将在 {SEND_RETRY_SECONDS}s 后重试: {type(e).__name__}: {e}")
        schedule_reminder_job(
            reminder_id, user_id, datetime.now() + timedelta(seconds=SEND_RETRY_SECONDS)
        )
        return

    print(f"[DEBUG] 已发送提醒 #{reminder_id} 给 {user_id}")
    delete_reminder(reminder_id)


# ===== Bot 连接后把数据库里的提醒重新挂载到调度器 =====
# 用 on_bot_connect 而不是 on_startup:反向 WS 下启动时 Bot 还没连上,
# 此时补发到点提醒会因为 get_bot() 失败而走重试逻辑。等连接建立后再恢复更稳。
driver = get_driver()


@driver.on_bot_connect
async def restore_reminders(bot: Bot):
    now = datetime.now()
    restored = 0
    overdue = 0
    for reminder in list_all_reminders():
        reminder_id = int(reminder["id"])
        # 已经在调度器里的任务(比如重连触发的二次恢复)跳过,避免把未来提醒重排到补发时间
        if scheduler.get_job(_job_id(reminder_id)) is not None:
            continue
        try:
            target_time = datetime.fromisoformat(reminder["remind_at"])
        except (TypeError, ValueError):
            print(f"[DEBUG] 提醒 #{reminder_id} 时间格式异常,跳过: {reminder['remind_at']}")
            continue

        if target_time <= now:
            # 停机期间已经到点的提醒,稍微延后立即补发
            target_time = now + timedelta(seconds=5)
            overdue += 1
        schedule_reminder_job(reminder_id, int(reminder["user_id"]), target_time)
        restored += 1

    if restored:
        print(f"[DEBUG] 已从数据库恢复 {restored} 条提醒(其中 {overdue} 条到点补发)")


# ===== /我的提醒 =====
list_cmd = on_command("我的提醒", aliases={"提醒列表"}, priority=1, block=True)

@list_cmd.handle()
async def handle_list(event: PrivateMessageEvent):
    user_id = event.user_id
    reminders = list_user_reminders(user_id)

    if not reminders:
        await list_cmd.send("你还没有任何提醒呢 ⌓‿⌓")
        return

    lines = ["📋 你的提醒列表:"]
    for r in reminders:
        try:
            time_display = datetime.fromisoformat(r["remind_at"]).strftime("%m月%d日 %H:%M")
        except (TypeError, ValueError):
            time_display = r["remind_at"]
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

    reminder = get_reminder(target_id)
    if reminder is None or int(reminder["user_id"]) != user_id:
        await cancel_cmd.send(f"找不到 #{target_id} 这条提醒")
        return

    # 取消定时任务
    try:
        scheduler.remove_job(_job_id(target_id))
    except Exception as e:
        print(f"[DEBUG] 取消定时任务失败 (可能已触发): {e}")

    delete_reminder(target_id)

    await cancel_cmd.send(f"已取消提醒 #{target_id}: {reminder['content']} ⌓‿⌓")
