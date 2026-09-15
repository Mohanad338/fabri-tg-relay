import os
import json
import time
import asyncio
import hashlib
import requests
from telethon import TelegramClient, events
from telethon.sessions import StringSession

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = os.environ["TG_SESSION"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GEMINI_KEY = os.environ["GEMINI_API_KEY"].strip()
TARGET_CHANNEL = os.environ["TARGET_CHANNEL"]
SOURCE_CHANNEL = "fabrizioromanotg"

STATE_FILE = "last_id.json"
MAX_RUNTIME_SECONDS = 5 * 3600 + 40 * 60

def load_last_id():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f).get("last_id", 0)
    return 0

def save_last_id(msg_id):
    with open(STATE_FILE, "w") as f:
        json.dump({"last_id": msg_id}, f)

def text_hash(text):
    normalized = " ".join(text.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def git_commit_state():
    import subprocess
    subprocess.run(["git", "config", "user.name", "github-actions"])
    subprocess.run(["git", "config", "user.email", "actions@github.com"])
    subprocess.run(["git", "add", "last_id.json"])
    commit = subprocess.run(["git", "commit", "-m", "update last_id"], capture_output=True, text=True)
    print("GIT COMMIT:", commit.returncode, commit.stdout.strip(), commit.stderr.strip())

    for attempt in range(3):
        push = subprocess.run(["git", "push"], capture_output=True, text=True)
        if push.returncode == 0:
            print("GIT PUSH: success")
            return
        print(f"GIT PUSH attempt {attempt+1} FAILED:", push.stderr.strip())
        subprocess.run(["git", "pull", "--rebase", "--autostash"])
    print("GIT PUSH: all attempts failed")

def process_with_gemini(text):
    if not text:
        return {"should_post": False, "text": ""}

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent"
    headers = {
        "x-goog-api-key": GEMINI_KEY,
        "Content-Type": "application/json"
    }

    prompt = (
        "أنت محرر أخبار رياضية متخصص بأخبار الانتقالات لصحفي يدعى فابريزيو رومانو. "
        "مهمتك تقييم المنشور التالي وإعادة صياغته إذا لزم.\n\n"
        "قواعد النشر — تُنشر دائماً بالكامل بدون استثناء (should_post=true تلقائياً) في هذي الحالات:\n"
        "1. تغطية المباريات المباشرة بكل تفاصيلها: بداية المباراة، أهداف، أحداث أثناء اللعب، نهاية المباراة (Full-time / النتيجة النهائية).\n"
        "2. التشكيلة الرسمية لمباراة (Starting XI / lineup).\n"
        "3. إحصائيات أداء لاعب بعد مباراة أو خلال فترة معينة (أهداف، تمريرات حاسمة، مساهمات تهديفية، أرقام قياسية).\n"
        "4. جائزة أو تصويت أفضل لاعب بالمباراة (Man of the Match / Player of the Match).\n"
        "5. أي منشور فيه عبارة \"Here We Go\" أو ما يعادلها (تأكيد اكتمال صفقة انتقال رسمياً).\n\n"
        "لباقي أخبار الانتقالات والتصريحات (غير المرتبطة بمباراة مباشرة)، كن متوسط التساهل لا متشدداً: "
        "انشر أي خبر فيه تقدم حقيقي بصفقة (مفاوضات جدية، عرض رسمي، اقتراب من الاتفاق، اكتمال، تجديد عقد)، انتقال أو اهتمام بلاعب أو نادٍ معروف، "
        "أو تصريح من مصدر داخل النادي أو من اللاعب نفسه، أو إصابة لاعب أساسي. "
        "لا ترفض خبراً إلا إذا كان فعلاً سطحياً جداً: تكهنات صحفية عامة بدون أي مصدر أو تفاصيل، أو تكرار حرفي لخبر سبق نشره بدون أي جديد.\n\n"
        "أعد النتيجة بصيغة JSON فقط بدون أي نص إضافي أو علامات markdown، بهذا الشكل بالضبط:\n"
        '{"should_post": true أو false, "text": "النص المعاد صياغته بالعربية"}\n\n'
        "شروط النص المعاد صياغته لو should_post=true:\n"
        "- مختصر وواضح جداً، جملتين إلى ثلاث جمل كحد أقصى (إلا لو كان تغطية مباراة أو إحصائية تفصيلية، حينها اختصر بدون حذف معلومة جوهرية).\n"
        "- عربي فصيح صحفي طبيعي، كأنه مكتوب أصلاً بالعربي وليس ترجمة.\n"
        "- احتفظ بكل الأسماء والأرقام والحقائق كما هي بدقة.\n"
        "- عبارة \"Here We Go\" تحديداً: اكتبها بالإنجليزي حرفياً كما هي داخل النص العربي، لا تترجمها أبداً إلى أي صيغة عربية.\n"
        "- بدون مقدمات أو تعليقات إضافية.\n\n"
        "لو should_post=false، اجعل text فارغاً.\n\n"
        "المنشور:\n" + text
    )

    body = {"contents": [{"parts": [{"text": prompt}]}]}
    r = requests.post(url, json=body, headers=headers, timeout=30)
    if r.status_code != 200:
        print("FULL ERROR RESPONSE:", r.text)
    r.raise_for_status()
    data = r.json()
    raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()

    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()

    try:
        result = json.loads(raw)
        return {
            "should_post": bool(result.get("should_post", False)),
            "text": result.get("text", "").strip()
        }
    except json.JSONDecodeError:
        print("JSON PARSE FAILED, raw response:", raw)
        return {"should_post": False, "text": ""}

async def is_duplicate_in_channel(client, text):
    target_hash = text_hash(text)
    try:
        recent = await client.get_messages(TARGET_CHANNEL, limit=30)
    except Exception as e:
        print("DEBUG could not fetch target channel history for dedup check:", e)
        return False
    for m in recent:
        existing_text = m.message or m.raw_text or ""
        if existing_text and text_hash(existing_text) == target_hash:
            return True
    return False

def send_to_telegram(text, photo_path=None):
    if photo_path:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        with open(photo_path, "rb") as f:
            r = requests.post(url, data={"chat_id": TARGET_CHANNEL, "caption": text}, files={"photo": f}, timeout=30)
    else:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        r = requests.post(url, data={"chat_id": TARGET_CHANNEL, "text": text}, timeout=30)
    print("TELEGRAM SEND STATUS:", r.status_code)
    print("TELEGRAM SEND RESPONSE:", r.text)
    try:
        return r.json().get("result", {}).get("message_id")
    except Exception:
        return None

def delete_from_telegram(message_id):
    if not message_id:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
    r = requests.post(url, data={"chat_id": TARGET_CHANNEL, "message_id": message_id}, timeout=30)
    print("TELEGRAM DELETE STATUS:", r.status_code, r.text)

async def download_photo_with_retries(client, msg, attempts=4, delay_seconds=5):
    for attempt in range(1, attempts + 1):
        try:
            photo_path = await client.download_media(msg, file="temp_photo.jpg")
            if photo_path:
                return photo_path
        except Exception as e:
            print(f"DEBUG photo download attempt {attempt} failed:", e)
        if attempt < attempts:
            await asyncio.sleep(delay_seconds)
    return None

client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)
state = {"last_id": load_last_id()}

async def handle_message(msg, client):
    text = msg.message or ""

    if msg.id > state["last_id"]:
        state["last_id"] = msg.id
        save_last_id(state["last_id"])
        git_commit_state()

    if not text.strip():
        return

    result = process_with_gemini(text)
    print("DEBUG should_post:", result["should_post"], "| id:", msg.id)

    if not result["should_post"] or not result["text"]:
        return

    photo_path = None
    if msg.media:
        photo_path = await download_photo_with_retries(client, msg)
        if not photo_path:
            print("DEBUG photo download failed after retries, skipping post (photo mandatory when source has one):", msg.id)
            return

    if await is_duplicate_in_channel(client, result["text"]):
        print("DEBUG duplicate found in target channel, skipping post:", msg.id)
        if photo_path:
            os.remove(photo_path)
        return

    send_to_telegram(result["text"], photo_path)

    if photo_path and os.path.exists(photo_path):
        os.remove(photo_path)

@client.on(events.NewMessage(chats=SOURCE_CHANNEL))
async def live_handler(event):
    await handle_message(event.message, client)

async def catch_up():
    last_id = load_last_id()
    messages = await client.get_messages(SOURCE_CHANNEL, min_id=last_id, limit=10)
    messages = list(reversed(messages))
    print("DEBUG catch-up messages found:", len(messages))
    for msg in messages:
        await handle_message(msg, client)
        await asyncio.sleep(2)

async def main():
    await client.start()
    await catch_up()
    print("DEBUG live listening started")

    start_time = time.time()
    while time.time() - start_time < MAX_RUNTIME_SECONDS:
        await asyncio.sleep(30)

    print("DEBUG runtime limit reached, disconnecting for scheduled restart")
    await client.disconnect()

asyncio.run(main())
