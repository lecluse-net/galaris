"""Manually test the complete messaging module with OneBot and MessengerHub.

The script exercises every messaging feature in isolation through a local WebSocket
simulation. Run it through the ``/tests/manual/messenger`` endpoint.
"""

from __future__ import annotations

from devtools import debug
from bridge.one_bot import OneBot  # Low-level OneBot driver test.


# ============================================================================
# Main test entry point.
# ============================================================================

async def send_group_msg()-> None :
    #async def send_group_msg(platform: str, group_id: str, message: Any) -> Any:
    pass

async def send_private_msg()-> None :
    #async def send_private_msg(platform: str, user_id: str, message: Any) -> Any:
    pass

async def delete_msg()-> None :
    #async def delete_msg(platform: str, message_id: str) -> Any:
    pass

async def get_group_list()-> None :
    #async def get_group_list(platform: str) -> Any:
    debug(await one_bot.get_group_list())
    pass

async def create_group()-> None :
    #async def create_group(platform: str, group_name: str, **kwargs) -> Any:
    await one_bot.create_group('essai1')
    pass

async def set_group_add()-> None :
    #async def set_group_add(platform: str, group_id: str, user_id: str) -> Any:
    pass

async def set_group_kick()-> None :
    #async def set_group_kick(platform: str, group_id: str, user_id: str) -> Any:
    pass

async def search_users()-> None :
    #async def search_users(platform: str, query: str) -> Any:
    pass

async def get_group_msg_history()-> None :
    #async def get_group_msg_history(platform: str, group_id: str) -> Any:
    pass

async def get_unread_messages()-> None :
    #async def get_unread_messages(platform: str, group_id: str) -> Any:
    pass

async def set_msg_emoji_like()-> None :
    #async def set_msg_emoji_like(platform: str, message_id: str, emoji: str    ) -> Any:
    pass

async def upload_group_file()-> None :
    #async def upload_group_file(self, platform: str, group_id: str, file: str) -> Any:
    pass

async def get_stranger_info()-> None :
    #async def get_stranger_info(self, platform: str, user_id: str) -> Any:
    pass

async def get_file()-> None :
    #async def get_file(self, platform: str, file_id: str) -> Any:
    pass

async def send_display_status()-> None :
    #async def send_display_status( platform: str, target_id: str, status: str) -> Any:
    pass

async def mark_group_msg_as_read()-> None :
    #async def mark_group_msg_as_read(self, platform: str, group_id: str) -> Any:
    pass

async def get_group_info()-> None :
    #async def get_group_info(self, platform: str, group_id: str) -> Any:
    pass

async def set_group_pin()-> None :
    #async def set_group_pin(platform: str, group_id: str, message_id: str, unpin: bool = False) -> Any
    pass

global one_bot

async def main() -> None:
    global one_bot
    
    one_bot = await OneBot.from_connection_id(1)
    
    await get_group_list()
    #create_group()
