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

MAX_PHOTO_SIZE_MB = 12

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("ent-bot")
upload_app = Flask(__name__)


PROMPT = """
Ты помощник для подготовки к ЕНТ по математике, информатике и истории Казахстана.
Распознай задачу на изображении и реши ее.

Верни строго одну строку:
ОТВЕТ: A | РЕШЕНИЕ: короткое пояснение до 20-30 слов

Если варианты ответа буквенные, верни букву. Если ответа с вариантами нет, верни число/текст.
Без markdown, без длинных рассуждений, без дополнительных строк.
""".strip()


@upload_app.get("/")
def health_check():
    return jsonify({"ok": True, "service": "ent-solver-bot"})


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
        if len(words) > 30:
            solution = " ".join(words[:30])
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
                max_output_tokens=120,
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
        "max_tokens": 120,
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


@upload_app.post("/upload")
def upload_screenshot():
    chat_id = request.args.get("chat_id", "").strip()
    secret = request.args.get("secret", "").strip()

    if UPLOAD_SECRET and secret != UPLOAD_SECRET:
        return jsonify({"ok": False, "error": "bad secret"}), 403

    if not chat_id:
        return jsonify({"ok": False, "error": "chat_id is required"}), 400

    image_bytes = request.get_data()
    if not image_bytes:
        return jsonify({"ok": False, "error": "empty file body"}), 400

    if len(image_bytes) > MAX_PHOTO_SIZE_MB * 1024 * 1024:
        return jsonify({"ok": False, "error": "file is too large"}), 413

    mime_type = request.headers.get("Content-Type") or "image/jpeg"
    if "png" in mime_type.lower():
        mime_type = "image/png"
    else:
        mime_type = "image/jpeg"

    try:
        answer = asyncio.run(solve_image(image_bytes, mime_type))
        send_telegram_message(chat_id, answer)
        return jsonify({"ok": True, "answer": answer})
    except Exception:
        logger.exception("Upload endpoint failed")
        try:
            send_telegram_message(
                chat_id,
                "ОТВЕТ: ? | РЕШЕНИЕ: Ошибка обработки upload-запроса. Проверьте сервер и ключи.",
            )
        except Exception:
            logger.exception("Could not notify user after upload failure")
        return jsonify({"ok": False, "error": "processing failed"}), 500


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
