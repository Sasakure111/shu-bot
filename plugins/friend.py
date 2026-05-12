import asyncio
from nonebot import on_request
from nonebot.adapters.onebot.v11 import Bot, FriendRequestEvent

from .state import recently_added_friends

friend_req = on_request(priority=5, block=True)

processed_flags = set()

@friend_req.handle()
async def handle_friend_request(bot: Bot, event: FriendRequestEvent):
    user_id = event.user_id
    comment = event.comment or ""
    flag = event.flag
    
    if flag in processed_flags:
        print(f"[DEBUG] 请求 {flag} 已处理过,跳过")
        return
    processed_flags.add(flag)
    
    print(f"[DEBUG] 好友请求: QQ={user_id}, 验证消息={comment}")
    
    # 把这个 user_id 加入"刚加好友"集合,屏蔽 echo.py 在 3 秒内的 AI 回复
    recently_added_friends.add(int(user_id))
    print(f"[DEBUG] 已加入忽略集合: {user_id}")
    
    await event.approve(bot)
    print(f"[DEBUG] 已自动通过 {user_id}")
    
    await asyncio.sleep(2)
    
    try:
        welcome_msg = "你好呀～我是OW ⌓‿⌓ 直接给我发消息就能聊天啦\n发送“/菜单”可以查看功能指令！"
        await bot.send_private_msg(user_id=int(user_id), message=welcome_msg)
        print(f"[DEBUG] 已发送欢迎消息给 {user_id}")
    except Exception as e:
        print(f"[DEBUG] 发送欢迎消息失败: {type(e).__name__}: {e}")
    
    # 10 秒后从忽略集合里移除,恢复正常 AI 聊天
    await asyncio.sleep(3)
    recently_added_friends.discard(int(user_id))
    print(f"[DEBUG] 已从忽略集合移除: {user_id}")