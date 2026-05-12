# 共享状态:刚加的好友(短期内忽略他们的消息)
recently_added_friends = set()

# 用户对话历史: { user_id: [{"role": "user/assistant", "content": "..."}, ...] }
chat_history = {}

# 每个用户最多保留多少轮对话(一轮 = user + assistant 两条)
MAX_HISTORY_TURNS = 35