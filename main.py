import os
import time
import uuid
import base64
import asyncio
import requests
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
#   ---------------------------------------------------- Cooldown
#
def can_make_request(user_id, cooldown_seconds=3600):
    """
    Проверяет, может ли пользователь сделать запрос.
    cooldown_seconds: время ожидания между запросами (по умолчанию 1 час = 3600 секунд)
    Возвращает True если можно делать запрос, False если нужно ждать
    """
    current_time = time.time()

    if user_id not in user_last_request:
        user_last_request[user_id] = current_time
        return True

    last_request_time = user_last_request[user_id]
    time_since_last_request = current_time - last_request_time

    if time_since_last_request >= cooldown_seconds:
        user_last_request[user_id] = current_time
        return True
    else:
        return False


def get_remaining_time(user_id, cooldown_seconds=3600):
    """
    Возвращает оставшееся время до возможности следующего запроса в минутах
    """
    if user_id not in user_last_request:
        return 0

    current_time = time.time()
    last_request_time = user_last_request[user_id]
    time_since_last_request = current_time - last_request_time

    if time_since_last_request >= cooldown_seconds:
        return 0
    else:
        remaining_seconds = cooldown_seconds - time_since_last_request
        return int(remaining_seconds / 60)  # Возвращаем в минутах

#
#   ---------------------------------------------------- GigaChat
#
def get_gigachat_token(auth_token, scope='GIGACHAT_API_PERS'):
    """
    Выполняет POST-запрос к эндпоинту, который выдает токен.
    """
    rq_uid = str(uuid.uuid4())
    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"

    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
        'RqUID': rq_uid,
        'Authorization': f'Basic {auth_token}'
    }

    payload = {
        'scope': scope
    }

    try:
        response = requests.post(url, headers=headers, data=payload, verify=False)
        response.raise_for_status()
        return response
    except requests.RequestException as e:
        print(f"Ошибка при получении токена: {str(e)}")
        raise


def get_access_token():
    """
    Получает или обновляет токен доступа GigaChat
    """
    global access_token, token_expires_at
    now = time.time()

    if access_token is None or now >= token_expires_at - 300:
        try:
            response = get_gigachat_token(GIGA_AUTH_KEY, GIGA_SCOPE)
            token_data = response.json()
            access_token = token_data['access_token']

            if 'expires_at' in token_data:
                token_expires_at = token_data['expires_at']
            else:
                token_expires_at = now + 1800

            print("Токен GigaChat успешно получен")

        except Exception as e:
            print("Ошибка при получении токена:", e)
            raise

    return access_token

#
#   ---------------------------------------------------- Kandinsky
#

async def generate_cat_image(prompt):
    """
    Генерирует изображение кота с помощью Kandinsky API
    Возвращает bytes с изображением
    """
    if not KANDINSKY_API_KEY or not KANDINSKY_SECRET_KEY:
        raise ValueError("Kandinsky API ключи не настроены")

    async_client = AsyncFBClient(x_key=KANDINSKY_API_KEY, x_secret=KANDINSKY_SECRET_KEY)

    try:
        # 1. Получаем pipeline для генерации изображений
        pipelines = await async_client.get_pipelines_by_type(PipelineType.TEXT2IMAGE)
        text2image_pipeline = pipelines[0]
        print(f"Using Kandinsky pipeline: {text2image_pipeline.name}")

        # 2. Запускаем генерацию
        run_result = await async_client.run_pipeline(
            pipeline_id=text2image_pipeline.id,
            prompt=f"Красивый кот породы {prompt}, фотореалистичное изображение, высокое качество"
        )

        # 3. Ждем завершения генерации
        print(f"Генерация изображения начата, UUID: {run_result.uuid}")
        final_status = await async_client.wait_for_completion(
            request_id=run_result.uuid,
            initial_delay=run_result.status_time
        )

        if final_status.status == 'DONE':
            print("Генерация изображения успешна!")

            if final_status.result and final_status.result.files:
                # Декодируем base64 в bytes
                image_data_base64 = final_status.result.files[0]
                image_data = base64.b64decode(image_data_base64)
                return image_data
            else:
                raise Exception("No images generated")
        else:
            raise Exception(f"Generation failed with status: {final_status.status}")

    except Exception as e:
        print(f"Ошибка при генерации изображения: {e}")
        raise


async def get_cat_breed_from_gigachat():
    """
    Получает описание породы кота от GigaChat
    """
    prompt = "Назови одну случайную породу кота с случайным прилагательным. Ответ должен быть кратким, только название породы с прилагательным. Например: 'Печальный мейн-кун' или 'Клоунский сиамец'. Не добавляй никаких дополнительных слов."

    try:
        token = get_access_token()

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": "GigaChat",
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 50
        }

        response = requests.post(
            GIGA_CHAT_URL,
            json=payload,
            headers=headers,
            verify=False,
            timeout=30
        )
        response.raise_for_status()

        response_data = response.json()
        cat_breed = response_data["choices"][0]["message"]["content"].strip()
        print("Ответ от GigaChat:", cat_breed)
        return cat_breed

    except Exception as e:
        print("Ошибка при запросе к GigaChat:", e)
        raise


#
#   ---------------------------------------------------- UX/Events
#

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    print(f"[START] chat_id={chat_id}, user_id={user_id}")

    kb = [[KeyboardButton("Сказать породу кота")]]
    markup = ReplyKeyboardMarkup(kb, resize_keyboard=True)

    await update.message.reply_text(
        "Нажми кнопку, чтобы я назвал породу случайного кота с прилагательным и показал его изображение!",
        reply_markup=markup
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команды:\n/start - начать"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    text = update.message.text
    print(f"[MSG] chat_id={chat_id}, user_id={user_id}, text={text}")

    if text == "Сказать породу кота":
        # Отправляем сообщение о начале обработки
        processing_message = await update.message.reply_text("🐱 Генерирую породу кота и изображение...")
        
        try:
            # Получаем породу кота от GigaChat
            cat_breed = await get_cat_breed_from_gigachat()
            
            # Генерируем изображение асинхронно
            image_data = await generate_cat_image(cat_breed)
            
            # Удаляем сообщение о обработке
            await processing_message.delete()
            
            # Отправляем изображение с подписью
            await update.message.reply_photo(
                photo=image_data,
                caption=f"🎨 Сгенерированный кот: {cat_breed}",
                parse_mode='Markdown'
            )
            
        except Exception as e:
            # Удаляем сообщение о обработке в случае ошибки
            await processing_message.delete()
            
            error_message = f"Произошла ошибка: {str(e)}"
            print(error_message)
            
            # Если есть порода кота, но нет изображения
            if 'cat_breed' in locals():
                await update.message.reply_text(
                    f"Порода кота: {cat_breed}\n\nНо произошла ошибка при генерации изображения 😿"
                )
            else:
                await update.message.reply_text(
                    "Извините, произошла ошибка при обработке запроса. Попробуйте еще раз."
                )
    else:
        await update.message.reply_text("Нажми кнопку, чтобы узнать породу кота и увидеть его изображение!")

#
#   ---------------------------------------------------- Main
#

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

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
