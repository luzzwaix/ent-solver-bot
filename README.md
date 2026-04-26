# ENT Telegram Solver Bot

Учебный Telegram-бот для хакатонного проекта: принимает фото тренировочной задачи ЕНТ, отправляет изображение в Gemini и возвращает короткий ответ.

Формат ответа:

```text
ОТВЕТ: A | РЕШЕНИЕ: короткое пояснение до 20-30 слов
```

## Почему Python

Python лучше всего подходит для такого прототипа: `python-telegram-bot` быстро запускается через polling, код короткий, деплой на Render/PythonAnywhere простой.

## Бесплатные/условно бесплатные ИИ

1. Gemini API через Google AI Studio: обычно лучший вариант для хакатона, хорошо читает изображения, есть бесплатные квоты.
2. OpenAI GPT-4o: сильный fallback для изображений, но бесплатный доступ зависит от аккаунта/кредитов.
3. OpenRouter: иногда дает бесплатные модели с vision, но стабильность и лимиты зависят от модели.
4. Groq: быстрый и часто бесплатный для текста, но vision-доступ зависит от актуальных моделей.

По официальной документации Google сейчас рекомендует пакет `google-genai`. Старый `google-generativeai` находится в legacy-режиме, поэтому в проекте используется `google-genai`.

## Создание бота в Telegram

1. Откройте Telegram.
2. Найдите `@BotFather`.
3. Отправьте команду `/newbot`.
4. Введите название бота, например `ENT Solver`.
5. Введите username, который заканчивается на `bot`, например `ent_solver_demo_bot`.
6. Скопируйте токен вида `123456:ABC...`.
7. Вставьте токен в `bot.py`:

```python
TELEGRAM_TOKEN = "ваш_токен"
```

Или задайте переменную окружения `TELEGRAM_TOKEN`.

## Получение Gemini API key

1. Откройте https://aistudio.google.com/app/apikey.
2. Войдите в Google-аккаунт.
3. Нажмите `Create API key`.
4. Скопируйте ключ.
5. Вставьте ключ в `bot.py`:

```python
GEMINI_API_KEY = "ваш_ключ"
```

Или задайте переменную окружения `GEMINI_API_KEY`.

По требованию проекта в коде стоит модель `gemini-1.5-pro`. Если API вернет ошибку, задайте:

```powershell
$env:GEMINI_MODEL="gemini-2.5-flash"
```

## OpenAI fallback

Fallback включится только если заполнен `OPENAI_API_KEY`.

```powershell
$env:OPENAI_API_KEY="ваш_openai_key"
```

Если OpenAI не нужен, оставьте пустым.

## Установка зависимостей

Рекомендуемый вариант:

```powershell
pip install -r requirements.txt
```

Если нужно строго одной строкой:

```powershell
pip install python-telegram-bot google-genai requests
```

Legacy-вариант из старых гайдов:

```powershell
pip install python-telegram-bot google-generativeai requests
```

Для этого проекта нужен именно `google-genai`.

## MacroDroid без Wi-Fi: публичный upload URL

Если телефон будет на мобильном интернете, он не сможет отправить файл на локальный IP компьютера. Нужен публичный адрес:

1. Render/PythonAnywhere, где запущен `bot.py`.
2. Или временный туннель вроде ngrok/Cloudflare Tunnel к вашему ПК.

В `bot.py` есть endpoint:

```text
POST /upload?chat_id=ВАШ_CHAT_ID&secret=ВАШ_SECRET
```

Он принимает скриншот как сырое тело запроса, решает задачу через Gemini и отправляет ответ в Telegram.

Для защиты задайте секрет:

```powershell
$env:UPLOAD_SECRET="любая_длинная_строка"
```

На Render добавьте `UPLOAD_SECRET` в Environment.

Пример публичного URL:

```text
https://your-app.onrender.com/upload?chat_id=123456789&secret=любая_длинная_строка
```

В MacroDroid:

1. `HTTP-запрос`.
2. Метод: `POST`.
3. URL: публичный `/upload`.
4. Вкладка `Тело сообщения`.
5. Выберите `Файл`.
6. В поле файла укажите последний скриншот:

```text
/storage/emulated/0/DCIM/Screenshots/{trigger_that_fired}
```

или:

```text
/storage/emulated/0/Pictures/Screenshots/{trigger_that_fired}
```

Так MacroDroid не обязан поддерживать Telegram `multipart/form-data`: он просто отправляет файл вашему серверу.

## Запуск

```powershell
python bot.py
```

После запуска откройте своего бота в Telegram, нажмите `/start` и отправьте фото задачи.

## Как узнать chat_id через getUpdates

Самый простой способ: запустите бота и отправьте ему команду:

```text
/id
```

Бот ответит:

```text
Ваш chat_id: 123456789
```

Альтернативный способ через Telegram API:

1. Напишите любое сообщение своему боту в Telegram.
2. Откройте ссылку в браузере, заменив токен:

```text
https://api.telegram.org/botВАШ_ТОКЕН/getUpdates
```

3. Найдите поле:

```json
"chat":{"id":123456789}
```

`123456789` и есть ваш `chat_id`.

## Android: Tasker для автоматической отправки тренировочных скриншотов

Используйте только для своих учебных материалов и демо хакатона.

Итоговая схема:

```text
Скриншот учебной задачи
→ Tasker видит новый файл
→ Tasker отправляет фото боту
→ бот отправляет изображение в Gemini
→ Gemini решает
→ бот присылает уведомление в Telegram
```

1. Установите Tasker.
2. Создайте новый `Profile`.
3. Выберите `Event`.
4. Выберите `File Modified` или `Folder Monitor`.
5. Укажите папку скриншотов:

```text
/storage/emulated/0/Pictures/Screenshots
```

На некоторых телефонах путь может быть:

```text
/storage/emulated/0/DCIM/Screenshots
```

6. Создайте новую `Task`, например `Send Screenshot To Bot`.
7. Добавьте действие `Wait` на 1-2 секунды, чтобы файл успел сохраниться.
8. Добавьте действие `List Files`.
9. Directory: папка скриншотов.
10. Match: `*.jpg/*.png` или просто оставьте пустым.
11. Sort Select: `Modification Date, Reverse`.
12. Variable Array: `%files`.
13. Добавьте действие `HTTP Request`.
14. Method: `POST`.
15. URL:

```text
https://api.telegram.org/botВАШ_ТЕЛЕГРАМ_ТОКЕН/sendPhoto
```

16. Body: `Form-Data`.
17. Добавьте form-data поля:

```text
chat_id = ВАШ_CHAT_ID
photo = %files1
```

Для поля `photo` выберите тип `File`, если Tasker показывает такой переключатель.

18. Сохраните профиль и сделайте тестовый скриншот тренировочной задачи.

Если Tasker не подставляет `%files1` как файл, установите AutoTools или используйте действие `HTTP Post` с multipart/form-data.

## iPhone/iOS

iOS не дает Tasker и не разрешает полностью фоновую отправку каждого нового скриншота в Telegram Bot API. Рабочий учебный вариант:

1. Откройте приложение `Команды` / `Shortcuts`.
2. Создайте shortcut `Send Screenshot To Bot`.
3. Добавьте действие `Получить последние фото` / `Get Latest Photos`.
4. Количество: `1`.
5. Добавьте действие `Получить содержимое URL` / `Get Contents of URL`.
6. URL:

```text
https://api.telegram.org/botВАШ_ТЕЛЕГРАМ_ТОКЕН/sendPhoto
```

7. Method: `POST`.
8. Request Body: `Form`.
9. Поля:

```text
chat_id = ВАШ_CHAT_ID
photo = результат Get Latest Photos
```

10. Запускайте shortcut вручную, через виджет, Back Tap или Siri.

Полностью автоматический триггер "после каждого скриншота" на iOS обычно недоступен без сторонних обходных решений.

## Render

1. Загрузите проект на GitHub.
2. Создайте Render `Web Service`.
3. Build command:

```bash
pip install -r requirements.txt
```

4. Start command:

```bash
python bot.py
```

5. В `Environment` добавьте:

```text
TELEGRAM_TOKEN
GEMINI_API_KEY
OPENAI_API_KEY
GEMINI_MODEL
```

Для polling веб-порт не нужен, но Render Web Service может ожидать открытый порт. Для стабильного бесплатного демо проще запускать локально или на PythonAnywhere.

## PythonAnywhere

1. Загрузите файлы `bot.py` и `requirements.txt`.
2. Откройте Bash console.
3. Выполните:

```bash
pip install --user -r requirements.txt
python bot.py
```

Для постоянной работы настройте `Always-on task`, если он доступен в вашем тарифе.

## Частые ошибки

1. `TELEGRAM_TOKEN is empty`: вставьте токен в `bot.py` или переменную окружения.
2. Gemini вернул 404 по модели: задайте `GEMINI_MODEL=gemini-2.5-flash`.
3. Бот отвечает, что принимает только фото: отправляйте изображение как фото, не как файл.
4. Tasker не отправляет фото: проверьте `chat_id`, токен, разрешение на доступ к файлам и multipart/form-data.
