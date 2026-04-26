import asyncio
import base64
import logging
import os
import re
import threading
from io import BytesIO

import requests
from flask import Flask, jsonify, request
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters


# Set these in Render Environment or in your local terminal.
# Do not hardcode real API keys in this file.
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# The hackathon requirement says gemini-1.5-pro. If it is unavailable,
# set GEMINI_MODEL=gemini-2.5-flash in Render Environment.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

UPLOAD_SECRET = os.getenv("UPLOAD_SECRET", "")
UPLOAD_SERVER_ENABLED = os.getenv("UPLOAD_SERVER_ENABLED", "1") == "1"
UPLOAD_HOST = os.getenv("UPLOAD_HOST", "0.0.0.0")
UPLOAD_PORT = int(os.getenv("PORT", os.getenv("UPLOAD_PORT", "8080")))
DEFAULT_POLLING_ENABLED = "0" if os.getenv("RENDER") or os.getenv("PORT") else "1"
TELEGRAM_POLLING_ENABLED = os.getenv(
    "TELEGRAM_POLLING_ENABLED",
    DEFAULT_POLLING_ENABLED,
) == "1"

MAX_PHOTO_SIZE_MB = 12

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("ent-bot")
upload_app = Flask(__name__)
recent_uploads = []


PROMPT = """
Сен ЕНТ тапсырмаларын шешетін өте мұқият көмекшісің: математика, информатика,
Қазақстан тарихы. Суреттен сұрақты және барлық жауап нұсқаларын оқы.

Міндетті ереже:
1. Алдымен есепті ішіңнен толық шығар.
   Скринде белгіленген radio/checkbox жауаптары болуы мүмкін. Оларды дұрыс деп
   қабылдама: бұл пайдаланушының таңдауы ғана. Міндетті түрде өзің есептеп тексер.
2. Сұрақ түрін анықта:
   - Математика/алгебра және информатикада №1-25 сұрақтарда әрқашан бір ғана
     жауап болады.
   - Математика/алгебра және информатикада №26-30 немесе қарапайым радио-батырма
     болса: бір ғана жауап таңда.
   - Математика/алгебра және информатикада №31-35, "Вопрос на соответствие",
     "сәйкестік", A) және B) жолдары болса: әр жолға
     сәйкес мәнді бер. Формат: ОТВЕТ: A - DDR; B - Serial ATA
   - Математика/алгебра және информатикада №36-40, "множественный выбор",
     checkbox, "бірнеше жауап", "мән(дер)і" болса:
     барлық дұрыс нұсқаларды таңда. Дұрыс жауап 1, 2, 3 немесе 4 болуы мүмкін.
     Артық нұсқа қоспа, бірақ дұрыс нұсқаны да тастап кетпе.
   - Қазақстан тарихы және математикалық сауаттылықта жоғарыдағы №26-40 ережесін
     автоматты қолданба; тек сұрақтың өзінде бірнеше жауап/сәйкестік анық жазылса
     ғана бірнеше жауап бер, әйтпесе бір жауап таңда.
3. Бірнеше таңдау болса, ОТВЕТ өрісіне ретімен жаз: 1 - A 2 - C 3 - E.
   Егер нұсқада әріптер көрінбесе, дұрыс нұсқалардың мәтінін қысқа жаз.
4. Жауап нұсқаларын оқы. Егер A/B/C/D/E әріптері көрінбесе, нұсқаларды жоғарыдан
   төмен немесе солдан оңға қарай сана: 1-нұсқа=A, 2-нұсқа=B, 3-нұсқа=C,
   4-нұсқа=D, 5-нұсқа=E.
5. Табылған нәтижені дәл сол нұсқамен салыстыр. ОТВЕТ өрісіндегі әріп пен
   РЕШЕНИЕ ішіндегі мән бір-біріне қайшы келмеуі керек.
6. Соңында өз жауабыңды тағы бір рет тексер: егер түсіндіру басқа нұсқаға
   апарса, әріпті түзет.
7. Егер скринде бір нұсқа белгіленіп тұрса және ол сенің шешіміңмен сәйкес
   келмесе, РЕШЕНИЕ ішінде қысқа айт: "Таңдалған A қате, дұрысы B, себебі ...".
   Егер белгіленген жауап дұрыс болса: "Таңдалған жауап дұрыс, себебі ...".

Жауапты тек бір жолмен қайтар:
ОТВЕТ: A | РЕШЕНИЕ: қазақша түсінікті қысқа шешім, 25-40 сөз

Екі жауап керек болса формат:
ОТВЕТ: 1 - A 2 - C | РЕШЕНИЕ: екі нұсқа неге дұрыс екенін қысқа түсіндір.

Үш/төрт жауап керек болса формат:
ОТВЕТ: 1 - A 2 - C 3 - E | РЕШЕНИЕ: таңдалғандардың ортақ дұрыс белгісін қысқа түсіндір.

Сәйкестік сұрағы болса формат:
ОТВЕТ: A - DDR; B - Serial ATA | РЕШЕНИЕ: әр сәйкестікті 1 сөйлеммен негізде.

Пәнге қарай түсіндіру стилі:
- Математика: ең керек 1-2 қадамды ғана жаз, формула қарапайым болсын, нәтиже нұсқамен қалай сәйкескенін көрсет.
- Информатика: негізгі ереже/алгоритмді және неге сол нұсқа екенін қысқа түсіндір.
- Қазақстан тарихы: датаны, тұлғаны, оқиғаны немесе себеп-салдарды қысқа, бірақ жеткілікті айт.

LaTeX/Markdown қолданба: жақшадағы LaTeX, frac, sqrt командалары сияқты белгілерді жазба.
Формуланы қарапайым мәтінмен жаз: sqrt(3)/3, pi/6, tan x <= ...
Артық кіріспе, кешірім, бірнеше жол жазба.
Егер скрин анық емес болса да, ең ықтимал жауапты таңда және қысқа себеп жаз.
""".strip()


@upload_app.get("/")
def health_check():
    return jsonify({"ok": True, "service": "ent-solver-bot"})


def remember_upload(event: dict) -> None:
    recent_uploads.append(event)
    del recent_uploads[:-20]


@upload_app.get("/debug/uploads")
def debug_uploads():
    secret = request.args.get("secret", "").strip()
    if UPLOAD_SECRET and secret != UPLOAD_SECRET:
        return jsonify({"ok": False, "error": "bad secret"}), 403
    return jsonify({"ok": True, "recent_uploads": recent_uploads})


def normalize_answer(text: str) -> str:
    text = " ".join((text or "").strip().split())
    if not text:
        return "ОТВЕТ: ? | РЕШЕНИЕ: Не удалось распознать ответ. Попробуйте более четкий скриншот."

    answer_match = re.search(r"ОТВЕТ\s*:\s*([^|]+)", text, flags=re.IGNORECASE)
    solution_match = re.search(r"РЕШЕНИЕ\s*:\s*(.+)", text, flags=re.IGNORECASE)

    if answer_match and solution_match:
        answer = answer_match.group(1).strip()
        solution = solution_match.group(1).strip()
        words = solution.split()
        if len(words) > 48:
            solution = " ".join(words[:48])
        return f"ОТВЕТ: {answer} | РЕШЕНИЕ: {solution}"

    return f"ОТВЕТ: ? | РЕШЕНИЕ: {text[:220]}"


async def solve_with_gemini(image_bytes: bytes, mime_type: str) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is empty")

    client = genai.Client(api_key=GEMINI_API_KEY)

    def call_gemini() -> str:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                PROMPT,
            ],
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=190,
            ),
        )
        return response.text or ""

    result = await asyncio.to_thread(call_gemini)
    return normalize_answer(result)


async def solve_with_openai(image_bytes: bytes, mime_type: str) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is empty")

    image_base64 = base64.b64encode(image_bytes).decode("utf-8")
    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{image_base64}"
                        },
                    },
                ],
            }
        ],
        "temperature": 0.1,
        "max_tokens": 190,
    }
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    def call_openai() -> str:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    result = await asyncio.to_thread(call_openai)
    return normalize_answer(result)


async def solve_image(image_bytes: bytes, mime_type: str) -> str:
    try:
        return await solve_with_gemini(image_bytes, mime_type)
    except Exception:
        logger.exception("Gemini failed")

    if not OPENAI_API_KEY:
        logger.warning("OpenAI fallback skipped: OPENAI_API_KEY is empty")
        return (
            "ОТВЕТ: ? | РЕШЕНИЕ: Gemini недоступен, а OPENAI_API_KEY не задан. "
            "Добавьте ключ OpenAI или проверьте Gemini."
        )

    try:
        return await solve_with_openai(image_bytes, mime_type)
    except Exception:
        logger.exception("OpenAI fallback failed")
        return (
            "ОТВЕТ: ? | РЕШЕНИЕ: Gemini и GPT-4o временно недоступны. "
            "Проверьте API ключи, модель и повторите запрос."
        )


def send_telegram_message(chat_id: str, text: str) -> None:
    response = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=30,
    )
    response.raise_for_status()


def process_uploaded_image(chat_id: str, image_bytes: bytes, mime_type: str, event: dict) -> None:
    try:
        answer = asyncio.run(solve_image(image_bytes, mime_type))
        send_telegram_message(chat_id, answer)
        event["status"] = "sent"
        event["answer_preview"] = answer[:120]
    except Exception:
        logger.exception("Upload background processing failed")
        event["status"] = "processing_failed"
        try:
            send_telegram_message(
                chat_id,
                "ОТВЕТ: ? | РЕШЕНИЕ: Ошибка обработки upload-запроса. Проверьте сервер и ключи.",
            )
        except Exception:
            logger.exception("Could not notify user after upload failure")


@upload_app.post("/upload")
def upload_screenshot():
    chat_id = request.args.get("chat_id", "").strip()
    secret = request.args.get("secret", "").strip()
    event = {
        "path": request.path,
        "chat_id_present": bool(chat_id),
        "secret_present": bool(secret),
        "content_type": request.headers.get("Content-Type"),
        "content_length": request.headers.get("Content-Length"),
    }

    if UPLOAD_SECRET and secret != UPLOAD_SECRET:
        event["status"] = "bad_secret"
        remember_upload(event)
        return jsonify({"ok": False, "error": "bad secret"}), 403

    if not chat_id:
        event["status"] = "missing_chat_id"
        remember_upload(event)
        return jsonify({"ok": False, "error": "chat_id is required"}), 400

    image_bytes = request.get_data()
    event["bytes_received"] = len(image_bytes)
    if not image_bytes:
        event["status"] = "empty_body"
        remember_upload(event)
        return jsonify({"ok": False, "error": "empty file body"}), 400

    if len(image_bytes) > MAX_PHOTO_SIZE_MB * 1024 * 1024:
        event["status"] = "too_large"
        remember_upload(event)
        return jsonify({"ok": False, "error": "file is too large"}), 413

    mime_type = request.headers.get("Content-Type") or "image/jpeg"
    if "png" in mime_type.lower():
        mime_type = "image/png"
    else:
        mime_type = "image/jpeg"

    event["status"] = "accepted"
    remember_upload(event)
    threading.Thread(
        target=process_uploaded_image,
        args=(chat_id, image_bytes, mime_type, event),
        daemon=True,
    ).start()
    return jsonify({"ok": True, "status": "accepted"})


def run_upload_server() -> None:
    logger.info("Upload server started on %s:%s", UPLOAD_HOST, UPLOAD_PORT)
    upload_app.run(host=UPLOAD_HOST, port=UPLOAD_PORT, debug=False, use_reloader=False)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Отправьте фото тренировочной задачи ЕНТ. Я верну ответ в формате: "
        "ОТВЕТ: A | РЕШЕНИЕ: краткое пояснение."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Бот обрабатывает только фото. Сделайте четкий скриншот задачи и отправьте его сюда."
    )


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat:
        await update.message.reply_text(f"Ваш chat_id: {update.effective_chat.id}")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.photo:
        return

    try:
        photo = message.photo[-1]
        file_size = photo.file_size or 0
        if file_size > MAX_PHOTO_SIZE_MB * 1024 * 1024:
            await message.reply_text(
                f"ОТВЕТ: ? | РЕШЕНИЕ: Фото больше {MAX_PHOTO_SIZE_MB} МБ. Отправьте меньший скриншот."
            )
            return

        status_message = await message.reply_text("Распознаю задачу...")
        telegram_file = await context.bot.get_file(photo.file_id)

        buffer = BytesIO()
        await telegram_file.download_to_memory(out=buffer)
        image_bytes = buffer.getvalue()

        answer = await solve_image(image_bytes, "image/jpeg")
        await status_message.edit_text(answer)
    except Exception:
        logger.exception("Photo handler failed")
        await message.reply_text(
            "ОТВЕТ: ? | РЕШЕНИЕ: Ошибка обработки фото. Попробуйте отправить скриншот еще раз."
        )


async def handle_non_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(
            "ОТВЕТ: ? | РЕШЕНИЕ: Бот принимает только фото задач."
        )


def main() -> None:
    if not TELEGRAM_TOKEN:
        raise RuntimeError(
            "TELEGRAM_TOKEN is empty. Set it in Render Environment or local environment variables."
        )

    if UPLOAD_SERVER_ENABLED and not TELEGRAM_POLLING_ENABLED:
        run_upload_server()
        return

    if UPLOAD_SERVER_ENABLED:
        threading.Thread(target=run_upload_server, daemon=True).start()

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(~filters.PHOTO, handle_non_photo))

    logger.info("Bot started with polling")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
