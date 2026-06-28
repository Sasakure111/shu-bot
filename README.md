# QQ Chat Bot

基于 [NoneBot2](https://nonebot.dev/) + OneBot V11 的多功能 QQ 机器人：AI 聊天、塔罗、运势、提醒、maimai 查分，以及宠物养成和 Roguelike 文字冒险。

## ✨ 功能一览

| 功能 | 指令 | 说明 |
| --- | --- | --- |
| 💬 AI 聊天 | 直接发消息 / `/闲聊` `/深聊` `/清空记忆` | 接入 DeepSeek，带上下文记忆；闲聊模式短回复，深聊模式认真回复 |
| 🎴 塔罗 | `/塔罗 <问题>` | 抽一张大阿尔卡那并由 AI 解读 |
| 🔮 运势 | `/今日运势` | 每人每天结果固定 |
| ⏰ 提醒 | `/提醒 <时间> <内容>`、`/我的提醒`、`/取消提醒 <编号>` | 支持 `HH:MM` / `30分钟后` / `2小时后`，持久化、重启不丢 |
| 🎵 maimai | `/b50 <水鱼用户名>` | 查询 diving-fish B50 |
| 🐾 宠物 | `/宠物` 查看子菜单 | 领养 / 打卡 / 玩耍 / 互动 / 捕捉野怪 / 公屏 Boss / 宠物对战 / 弃养 |
| ⚔️ 冒险 | `/冒险` | Roguelike 文字 RPG：选职业、骰子属性、战斗、商店、事件、Boss、转生 |

群聊里需要 **@机器人** 才会响应；私聊直接发即可。完整指令见 `/菜单`。

## 📦 前置依赖

- **Python** `>=3.10, <4.0`
- **一个 OneBot V11 实现**（如 [NapCat](https://github.com/NapNeko/NapCatQQ) / [Lagrange](https://github.com/LagrangeDev/Lagrange.Core) / go-cqhttp），用反向 WebSocket 连接本机器人
- **DeepSeek API Key**（聊天 / 塔罗 / 宠物互动需要）
- **水鱼查分器 token**（可选，仅 `/b50` 需要）

Python 依赖：

```
nonebot2[fastapi]>=2.5.0
nonebot-adapter-onebot>=2.4.6
nonebot-plugin-apscheduler>=0.5.0
openai
aiohttp
python-dotenv
```

安装：

```bash
# 推荐使用虚拟环境
python -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

# 安装项目及全部运行依赖
pip install -e .
```

## 🚀 快速开始

1. **配置环境变量**：复制 `.env.example` 为 `.env.prod`，填入你的 key。

   ```bash
   # Linux / macOS
   cp .env.example .env.prod
   # Windows PowerShell
   Copy-Item .env.example .env.prod
   ```

2. **配置人设**：复制 `config/persona.example.txt` 为 `config/persona.txt`，写入你想要的人设。
   （不创建也能跑，会回退到示例人设。）

   ```bash
   # Linux / macOS
   cp config/persona.example.txt config/persona.txt
   # Windows PowerShell
   Copy-Item config/persona.example.txt config/persona.txt
   ```

3. **启动 OneBot 实现**（NapCat 等），配置反向 WS 指向 `ONEBOT_WS_URLS`（默认 `ws://127.0.0.1:3001`）。

4. **运行机器人**：

   ```bash
   nb run
   ```

## ⚙️ 环境变量说明

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `DRIVER` | ✅ | NoneBot 驱动，默认 `~fastapi+~websockets` |
| `ONEBOT_WS_URLS` | ✅ | OneBot 反向 WS 地址，如 `["ws://127.0.0.1:3001"]` |
| `LOCALSTORE_USE_CWD` | ✅ | `true` 时数据存到当前目录 |
| `APSCHEDULER_AUTOSTART` | ✅ | `true`，定时任务（提醒、宠物播报）需要 |
| `DEEPSEEK_API_KEY` | ✅ | DeepSeek 密钥 |
| `DEEPSEEK_BASE_URL` | ✅ | DeepSeek 接口地址，默认 `https://api.deepseek.com` |
| `DIVING_FISH_TOKEN` | ⬜ | 水鱼查分器 token，仅 `/b50` 需要 |
| `MCP_BRIDGE_TOKEN` | ⬜ | 个人遥控桥接用，未使用可留空 |

## 📁 数据与隐私

- 聊天记录、宠物、冒险存档等数据保存在本地 `data/chat_history.sqlite3`（已在 `.gitignore` 中，不会上传）。
- `.env.prod`、`config/persona.txt` 也已忽略，请勿提交你的真实密钥。

## 📚 参考

- NoneBot2 文档：<https://nonebot.dev/>
