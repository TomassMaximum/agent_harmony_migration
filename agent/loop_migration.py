# 临时脚本用于迁移现有session到chat
import sys
sys.path.insert(0, '/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent')
from agent.chat_memory import ChatMemory

chat_memory = ChatMemory()
chats = chat_memory.list_chats()
if not chats:
    chat_id = chat_memory.create_chat(description="Legacy sessions")
    chat_memory.migrate_existing_sessions(chat_id)
    print(f"Created legacy chat: {chat_id}")
else:
    print(f"Existing chats: {chats}")
