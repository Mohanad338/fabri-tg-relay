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
HASH_FILE = "posted_hashes.json"
MAX_HASHES = 60
MAX_RUNTIME_SECONDS = 5 * 3600 + 40 * 60

def load_last_id():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f).get("last_id", 0)
    return 0

def save_last_id(msg_id):
    with open(STATE_FILE, "w") as f:
        json.dump({"last_id": msg_id}, f)

def load_posted_hashes():
    if os.path.exists(HASH_FILE):
        with open(HASH_FILE) as f:
            return json.load(f).get("hashes", [])
    return []

def save_posted_hashes(hashes):
    with open(HASH_FILE, "w") as f:
        json.dump({"hashes": hashes[-MAX_HASHES:]}, f)

def text_hash(text):
    normalized = " ".join(text.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def git_commit_state():
    import subprocess
    subprocess.run(["git", "config", "user.name", "github-actions"])
    subprocess.run(["git", "config", "user.email", "actions@github.com"])
    subprocess.run(["git", "add", "last_id.json", "posted_hashes.json"])
    commit = subprocess.run(["git", "commit", "-m", "update state"], capture_output=True, text=True)
    print("GIT COMMIT:", commit.returncode, commit.stdout.strip(), commit.stderr.strip())

    for attempt in range(3):
        push = subprocess.run(["git", "push"], capture_output=True, text=True)
        if push.returncode == 0:
            print("GIT PUSH: success")
            return
        print(f"GIT PUSH attempt {attempt+1} FAILED:", push.stderr.strip())
        subprocess.run(["git", "pull", "--rebase", "--autostash"])
    print("GIT PUSH: all attempts failed, state may not persist for this message")

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

client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)
state = {"last_id": load_last_id(), "hashes": load_posted_hashes()}

# Serializes message handling so catch_up and the live handler can never
# process two messages at the same instant (prevents double-processing races).
process_lock = asyncio.Lock()

async def handle_message(msg, client):
    async with process_lock:
        text = msg.message or ""

        if msg.id > state["last_id"]:
            state["last_id"] = msg.id
            save_last_id(state["last_id"])
            git_commit_state()

        if not text.strip():
            return

        # Hash the ORIGINAL source text, not the Gemini-rephrased output.
        # Gemini's output is non-deterministic, so hashing its output let the
        # same source message slip past dedup with a different hash each time.
        h = text_hash(text)
        if h in state["hashes"]:
            print("DEBUG duplicate source, skipping:", msg.id)
            return

        result = process_with_gemini(text)
        print("DEBUG should_post:", result["should_post"], "| id:", msg.id)

        if not result["should_post"] or not result["text"]:
            return

        photo_path = None
        if msg.media:
            try:
                photo_path = await client.download_media(msg, file="temp_photo.jpg")
            except Exception:
                photo_path = None

        send_to_telegram(result["text"], photo_path)

        state["hashes"].append(h)
        save_posted_hashes(state["hashes"])
        git_commit_state()

        if photo_path and os.path.exists(photo_path):
            os.remove(photo_path)

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

    # Register the live handler only AFTER catch_up finishes, so backlog
    # messages can never be picked up by both catch_up and the live listener
    # at the same time (that race was the other source of duplicate posts).
    async def live_handler(event):
        await handle_message(event.message, client)

    client.add_event_handler(live_handler, events.NewMessage(chats=SOURCE_CHANNEL))

    start_time = time.time()
    while time.time() - start_time < MAX_RUNTIME_SECONDS:
        await asyncio.sleep(30)

    print("DEBUG runtime limit reached, disconnecting for scheduled restart")
    await client.disconnect()

asyncio.run(main())
