from __future__ import annotations

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageEvent, MessageSegment


def should_ignore_group_message(event: MessageEvent) -> bool:
    return isinstance(event, GroupMessageEvent) and not event.to_me


def reply_message(event: MessageEvent, text: str) -> Message:
    if isinstance(event, GroupMessageEvent):
        return MessageSegment.reply(event.message_id) + Message(text)
    return Message(text)


def plain_text_without_bot_at(event: MessageEvent) -> str:
    message = event.message
    if isinstance(event, GroupMessageEvent):
        message = message.exclude("at")
    return message.extract_plain_text().strip()
