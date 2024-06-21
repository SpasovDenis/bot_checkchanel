import logging
import asyncio
from telethon import TelegramClient, events
from telethon.tl.types import ChannelParticipantsAdmins, UpdateChannelParticipant
import aiomysql
import aioschedule as schedule
from dotenv import load_dotenv
import os

# Ваши данные для подключения к API Telegram и базе данных

load_dotenv()
api_id = os.getenv('api_id')
api_hash = os.getenv('api_hash')
bot_token = os.getenv('bot_token')
session = os.getenv('session')
time = int(os.getenv('time'))
# chanell_id больше не нужен, так как id канала будет получен автоматически

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Создание асинхронного клиента Telethon
client = TelegramClient(session, api_id, api_hash)

channel_id = None
handler_active = True
# Обработчик событий для отслеживания добавления бота в канал

@client.on(events.Raw)
async def handler(event):
    global channel_id
    # Проверяем, что это обновление типа UpdateChannelParticipant
    if isinstance(event, UpdateChannelParticipant):
        # Получаем информацию о боте
        me = await client.get_me()
        # Проверяем, что бот был добавлен в канал
        if hasattr(event.new_participant, 'user_id') and event.new_participant.user_id == me.id:
            channel_id = event.channel_id
            print(f'Бот был добавлен в канал с ID: {channel_id}')
            # Передаем channel_id в другие функции
            # Отписываемся от событий Raw
            client.remove_event_handler(handler, events.Raw)



# Асинхронные функции для работы с базой данных и Telegram API
async def create_server_connection(host_name, user_name, user_password, db_name):
    connection = await aiomysql.connect(
        host= os.getenv('host'),
        user= os.getenv('user'),
        password= os.getenv('password'),
        db= os.getenv('db'),
        loop=asyncio.get_event_loop()
    )
    return connection

async def get_admin_id(client, channel):
    try:
        admins = await client.get_participants(channel, filter=ChannelParticipantsAdmins)
        return [admin.id for admin in admins] if admins else []
    except Exception as e:
        logging.error(f"An error occurred while getting admin list: {e}")
        return None


async def check_user_in_db(connection, username, user_id):
    TABLE_NAME = os.getenv('TABLE_NAME')
    USERNAME_COLUMN = os.getenv('USERNAME_COLUMN')
    USER_ID_COLUMN = os.getenv('USER_ID_COLUMN')
    cursor = await connection.cursor()
    query = f"SELECT EXISTS(SELECT 1 FROM `{TABLE_NAME}` WHERE `{USERNAME_COLUMN}` = %s OR `{USER_ID_COLUMN}` = %s)"
    await cursor.execute(query, (username, user_id))
    result = await cursor.fetchone()
    await cursor.close()
    return result[0]

async def get_channel_users(client, channel):
    all_users = []
    async for user in client.iter_participants(channel):
        all_users.append(user)
    return all_users

async def check_users(channel_id):
    if channel_id is None:
        logging.error("channel_id не инициализирован.")
        return
    try:
        host = os.getenv('host')
        user = os.getenv('user')
        password = os.getenv('password')
        db = os.getenv('db')
        connection = await create_server_connection(host, user, password, db)
        if connection is None:
            logging.error("Failed to connect to the database. Please check your credentials.")
            return
        channel = await client.get_entity(channel_id)
        users = await get_channel_users(client, channel)
        admin_ids = await get_admin_id(client, channel)
        if not admin_ids:
            logging.error("No admins found in the channel.")
            return
        for user in users:
            username = getattr(user, 'username', None)
            user_id = getattr(user, 'id', None)

            if not await check_user_in_db(connection, username, user_id):
                if username:
                    message = f"Пользователь @{username} не найден в базе данных."
                else:
                    message = f"Пользователь с id {user_id} не найден в базе данных."
                for admin_id in admin_ids:
                    user = await client.get_entity(admin_id)
                    if not user.bot:
                        await client.send_message(admin_id, message)
                    else:
                        logging.info(f"Skipping bot with ID {admin_id}")
            else:
                logging.info(f"Пользователь {username or user_id} найден в базе данных.")
    except Exception as e:
        logging.error(f"An error occurred: {e}")
    finally:
        if connection is not None:
            await connection.close()

# Асинхронная функция main


async def scheduled_job():
    # Ваш код для запланированной задачи
    await check_users(channel_id)

async def main():
    await client.start(bot_token=bot_token)
    client.add_event_handler(handler)
    schedule.every(time).seconds.do(scheduled_job)

    while True:
        try:
            # Создаем список задач из корутин, запланированных в schedule.jobs
            tasks = [asyncio.create_task(job.job_func()) for job in schedule.jobs]
            # Ожидаем выполнения всех задач
            await asyncio.gather(*tasks)
        except Exception as e:
            logging.error(f"Произошла ошибка: {e}")
            # Здесь можно добавить код для переподключения к базе данных или Telegram API
        finally:
            # Пауза перед следующей проверкой запланированных задач
            await asyncio.sleep(time)

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
