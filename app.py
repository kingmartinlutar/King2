import os
import re
from datetime import datetime
from typing import Dict, List

from pyrogram import Client, filters, types
from pymongo import MongoClient
from cryptography.fernet import Fernet

# Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
MONGO_URI = os.getenv("MONGO_URI")
ADMINS = list(map(int, os.getenv("ADMINS").split(",")))
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

# Initialize
app = Client("content_bridge", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo = MongoClient(MONGO_URI)
db = mongo["content_bridge"]
fernet = Fernet(ENCRYPTION_KEY)

# Session Management
def store_session(user_id: int, session: str):
    encrypted = fernet.encrypt(session.encode())
    db.sessions.update_one(
        {"user_id": user_id},
        {"$set": {"session": encrypted, "timestamp": datetime.now()}},
        upsert=True
    )

def get_session(user_id: int) -> str:
    doc = db.sessions.find_one({"user_id": user_id})
    return fernet.decrypt(doc["session"]).decode() if doc else None

# Login Flow
@app.on_message(filters.command("login"))
async def login_handler(client: Client, message: types.Message):
    user_id = message.from_user.id
    await message.reply("Please send your phone number in international format (+1234567890)")
    
    try:
        phone_number = await client.ask(user_id, "Please send your phone number", timeout=120)
        temp_client = Client(f"session_{user_id}", api_id=API_ID, api_hash=API_HASH)
        await temp_client.connect()
        
        sent_code = await temp_client.send_code(phone_number.text)
        await message.reply("Please send the verification code you received")
        
        code = await client.ask(user_id, "Enter verification code", timeout=120)
        signed_in = await temp_client.sign_in(phone_number.text, sent_code.phone_code_hash, code.text)
        
        session_string = await temp_client.export_session_string()
        store_session(user_id, session_string)
        await message.reply("✅ Login successful!")
        
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")
    finally:
        await temp_client.disconnect()

# Content Downloader
async def process_batch(user_id: int, chat_id: str, start: int, end: int):
    session = get_session(user_id)
    if not session:
        return "❌ No active session. Please /login first."
    
    async with Client(f"client_{user_id}", session_string=session) as user_client:
        messages = []
        for msg_id in range(start, end+1):
            try:
                msg = await user_client.get_messages(chat_id, msg_id)
                messages.append(msg)
            except:
                continue
        
        for msg in messages:
            if msg.media:
                await msg.copy(user_id)
            else:
                await app.send_message(user_id, msg.text)

# Message Handler
@app.on_message(filters.regex(r"https://t\.me/(.+)/(\d+)(?:-(\d+))?"))
async def link_handler(client: Client, message: types.Message):
    match = re.match(r"https://t\.me/(.+)/(\d+)(?:-(\d+))?", message.text)
    if not match:
        return
    
    chat_id = match.group(1)
    start = int(match.group(2))
    end = int(match.group(3)) if match.group(3) else start
    
    await message.reply(f"🚀 Processing {end - start + 1} messages...")
    await process_batch(message.from_user.id, chat_id, start, end)

# Admin Commands
@app.on_message(filters.command("broadcast") & filters.user(ADMINS))
async def broadcast_handler(client: Client, message: types.Message):
    users = [doc["user_id"] for doc in db.sessions.find()]
    text = message.text.split(" ", 1)[1]
    
    for user_id in users:
        try:
            await client.send_message(user_id, text)
        except:
            continue

# Run
app.run()
