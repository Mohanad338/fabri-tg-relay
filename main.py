import os
import json
import asyncio
import requests
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = os.environ["TG_SESSION"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
TARGET_CHANNEL = os.environ["TARGET_CHANNEL"]
SOURCE_CHANNEL = "fabrizioromanotg"

STATE_FILE = "last_id.json"

def load_last_id():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f).get("last_id", 0)
    return 0

def save_last_id(msg_id):
    with open(STATE_FILE, "w") as f:
        json.dump({"last_id": msg_id}, f)

def translate_to_arabic(text):
    if not text:
        return ""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    prompt = (
        "أعد صياغة الخبر الرياضي التالي بالعربية الفصحى الصحفية الطبيعية، "
        "كأنه مكتوب أصلاً بالعربي وليس مترجماً، حافظ على كل الأسماء والأرقام والحقائق كما هي، "
        "بدون أي مقدمات أو تعليقات إضافية، فقط النص المعاد صياغته:\n\n" + text
    )
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    r = requests.post(url, json=body, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()

def send_to_telegram(text, photo_path=None):
    if photo_path:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        with open(photo_path, "rb") as f:
            requests.post(url, data={"chat_id": TARGET_CHANNEL, "caption": text}, files={"photo": f}, timeout=30)
    else:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TARGET_CHANNEL, "text": text}, timeout=30)

async def main():
    client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)
    await client.start()

    last_id = load_last_id()
    new_last_id = last_id

    messages = await client.get_messages(SOURCE_CHANNEL, min_id=last_id, limit=10)
    messages = list(reversed(messages))

    for msg in messages:
        text = msg.message or ""
        if not text.strip():
            continue

        translated = translate_to_arabic(text)

        photo_path = None
        if msg.media:
            try:
                photo_path = await client.download_media(msg, file="temp_photo.jpg")
            except Exception:
                photo_path = None

        send_to_telegram(translated, photo_path)

        if photo_path and os.path.exists(photo_path):
            os.remove(photo_path)

        if msg.id > new_last_id:
            new_last_id = msg.id

    save_last_id(new_last_id)
    await client.disconnect()

asyncio.run(main())
