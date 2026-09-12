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
GEMINI_KEY = os.environ["GEMINI_API_KEY"].strip()
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

def process_with_gemini(text):
    """
    يرجع dict فيها:
      - should_post: True/False
      - text: النص المختصر بالعربي (فارغ لو should_post=False)
    """
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
        "قواعد النشر — تُنشر دائماً بدون استثناء (should_post=true تلقائياً) في هذي الحالات:\n"
        "1. تغطية المباريات المباشرة (نتائج، أهداف، أحداث أثناء مباراة جارية، تشكيلات رسمية للمباراة).\n"
        "2. نتيجة نهاية المباراة (Full-time / final score).\n"
        "3. إحصائيات أداء لاعب بعد مباراة أو خلال فترة معينة (أهداف، تمريرات حاسمة، مساهمات تهديفية، أرقام قياسية).\n"
        "4. أي منشور فيه عبارة \"Here We Go\" أو ما يعادلها (تأكيد اكتمال صفقة انتقال رسمياً).\n\n"
        "لباقي الأخبار (شائعات، اهتمام أولي، مفاوضات جارية، تصريحات عامة)، انشرها فقط إذا كانت مهمة فعلاً: "
        "صفقة قريبة الاكتمال، انتقال لاعب كبير أو نادي كبير، تصريح رسمي مباشر من مصدر موثوق داخل النادي، إصابة مؤثرة للاعب أساسي.\n"
        "تُعتبر غير مهمة وتُرفض: شائعات مبكرة بدون مصدر رسمي، اهتمام أولي بدون تفاوض فعلي، تكهنات صحفية عامة، "
        "تحديثات بسيطة لأخبار سبق نشرها بدون جديد حقيقي.\n\n"
        "أعد النتيجة بصيغة JSON فقط بدون أي نص إضافي أو علامات markdown، بهذا الشكل بالضبط:\n"
        '{"should_post": true أو false, "text": "النص المعاد صياغته بالعربية"}\n\n'
        "شروط النص المعاد صياغته لو should_post=true:\n"
        "- مختصر وواضح جداً، جملتين إلى ثلاث جمل كحد أقصى (إلا لو كان تغطية مباراة أو إحصائية تفصيلية، حينها اختصر بدون حذف معلومة جوهرية).\n"
        "- عربي فصيح صحفي طبيعي، كأنه مكتوب أصلاً بالعربي وليس ترجمة.\n"
        "- احتفظ بكل الأسماء والأرقام والحقائق كما هي بدقة.\n"
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

    # تنظيف احتمال وجود ```json``` حول النتيجة
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
        # في حال فشل التحليل، لا ننشر تحسباً بدل ما ننشر شي غير متوقع
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

async def main():
    client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)
    await client.start()

    last_id = load_last_id()
    new_last_id = last_id

    messages = await client.get_messages(SOURCE_CHANNEL, min_id=last_id, limit=10)
    messages = list(reversed(messages))

    print("DEBUG messages found:", len(messages))

    for msg in messages:
        text = msg.message or ""

        if msg.id > new_last_id:
            new_last_id = msg.id

        if not text.strip():
            continue

        result = process_with_gemini(text)
        print("DEBUG should_post:", result["should_post"], "| original len:", len(text))

        if not result["should_post"] or not result["text"]:
            continue

        photo_path = None
        if msg.media:
            try:
                photo_path = await client.download_media(msg, file="temp_photo.jpg")
            except Exception:
                photo_path = None

        send_to_telegram(result["text"], photo_path)

        if photo_path and os.path.exists(photo_path):
            os.remove(photo_path)

        await asyncio.sleep(2)  # تأخير بسيط لتفادي حد تلكرام عند نشر عدة منشورات متراكمة مرة وحدة

    save_last_id(new_last_id)
    await client.disconnect()

asyncio.run(main())
