import os
import time
import uuid
import base64
import asyncio
import requests
import threading
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from fusionbrain_sdk_python import AsyncFBClient, PipelineType

# Отключаем предупреждения о SSL (только для разработки)
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ------------------------------------------ Глобальные переменные для токена

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
GIGA_AUTH_KEY = os.getenv("GIGA_AUTH_KEY")
KANDINSKY_API_KEY = os.getenv("KANDINSKYAPIKEY")
KANDINSKY_SECRET_KEY = os.getenv("KANDINSKYSECRETKEY")
GIGA_SCOPE = os.getenv("GIGA_SCOPE", "GIGACHAT_API_PERS")
GIGA_CHAT_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

access_token = None
token_expires_at = 0
user_last_request = {}

#
#   ---------------------------------------------------- Token Auto-Refresh
#

def refresh_gigachat_token_sync():
    """Синхронная функция для обновления токена"""
    global access_token, token_expires_at
    try:
        print("Автоматическое обновление токена GigaChat...")
        response = get_gigachat_token(GIGA_AUTH_KEY, GIGA_SCOPE)
        token_data = response.json()
        access_token = token_data['access_token']
        
        if 'expires_at' in token_data:
            token_expires_at = token_data['expires_at']
        else:
            token_expires_at = time.time() + 1800  # 30 минут
            
        print(f"Токен GigaChat успешно обновлен. Действителен до: {time.ctime(token_expires_at)}")
    except Exception as e:
        print(f"Ошибка при автоматическом обновлении токена: {e}")

def token_refresh_worker():
    """Рабочий поток для обновления токена"""
    while True:
        refresh_gigachat_token_sync()
        # Ждем 25 минут перед следующим обновлением
        time.sleep(25 * 60)

def start_token_refresh_daemon():
    """Запускает демон для обновления токена в фоновом потоке"""
    thread = threading.Thread(target=token_refresh_worker, daemon=True)
    thread.start()
    print("Демон обновления токена запущен")

def get_gigachat_token(auth_token, scope='GIGACHAT_API_PERS'):
    """Выполняет POST-запрос к эндпоинту, который выдает токен."""
    rq_uid = str(uuid.uuid4())
    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"

    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
        'RqUID': rq_uid,
        'Authorization': f'Basic {auth_token}'
    }

    payload = {'scope': scope}

    try:
        response = requests.post(url, headers=headers, data=payload, verify=False)
        response.raise_for_status()
        return response
    except requests.RequestException as e:
        print(f"Ошибка при получении токена: {str(e)}")
        raise

def get_access_token():
    """Получает или обновляет токен доступа GigaChat"""
    global access_token, token_expires_at
    now = time.time()

    if access_token is None or now >= token_expires_at - 300:
        refresh_gigachat_token_sync()

    return access_token

# ... остальной код остается без изменений (функции can_make_request, get_remaining_time, 
# generate_cat_image, get_cat_breed_from_gigachat, start, help_command, handle_message)

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN отсутствует")
    if not GIGA_AUTH_KEY:
        raise ValueError("GIGA_AUTH_KEY отсутствует")
    if not KANDINSKY_API_KEY or not KANDINSKY_SECRET_KEY:
        print("Kandinsky API ключи не настроены. Генерация изображений будет недоступна.")

    # Проверяем подключение к GigaChat при старте
    try:
        print("Проверка подключения к GigaChat...")
        get_access_token()
        print("Подключение к GigaChat успешно!")
    except Exception as e:
        print(f"Ошибка подключения к GigaChat: {e}")

    # Запускаем демон обновления токена
    start_token_refresh_daemon()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
