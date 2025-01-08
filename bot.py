import logging
from telebot import TeleBot, types
from config import TOKEN, SENDER_USER_ID, RECEIVER_USER_ID, INFO_CHAT_ID  # Импортируем значения из config.py

bot = TeleBot(TOKEN)

# Глобальные переменные
task_counter = 1  # Номер задачи
task_status = {}  # Статусы задач
created_threads = {}  # Ветки задач
message_ids_in_chat = {}  # ID сообщений со статусами задач
pending_tasks = {}  # Задачи, ожидающие завершения ввода

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_full_name(user):
    """Получить полное имя пользователя."""
    return f"{user.first_name} {user.last_name}" if user.last_name else user.first_name

def create_forum_topic(task_number, short_topic):
    """Создает тему в форуме с уникальной иконкой."""
    icon_color = 7322096  # Задаем стандартный цвет иконки
    try:
        response = bot.create_forum_topic(
            chat_id=INFO_CHAT_ID,
            name=f"{task_number}. {short_topic}",  # Номер + краткая тема
            icon_color=icon_color
        )
        return response.message_thread_id
    except Exception as e:
        logger.error(f"Ошибка при создании темы: {e}")
        return None

def send_message_to_forum_thread(message, thread_id, photo=None):
    """Отправляет сообщение (и фото, если есть) в форумный тред."""
    try:
        if photo:
            bot.send_photo(chat_id=INFO_CHAT_ID, photo=photo, caption=message, message_thread_id=thread_id)
        else:
            bot.send_message(chat_id=INFO_CHAT_ID, text=message, message_thread_id=thread_id)
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения в тред форума: {e}")

def send_task_status_update(task_number):
    """Обновляет статус задачи в общем чате."""
    task_info = task_status[task_number]
    task_message = (
        f"*Задача #{task_number}*\n"  # Перенос строки после эмодзи
        f"📌 {task_info['topic']}\n"
        f"📝 {task_info['description']}\n"
        f"Статусы:\n"
    )

    for idx, (user, status_text) in enumerate(task_info['status'].items(), 1):
        task_message += f"{idx}. {user} — {status_text}\n"  # Каждый статус на новой строке

    try:
        if task_number in message_ids_in_chat:
            if task_info.get('photo'):
                bot.edit_message_caption(
                    caption=task_message, chat_id=INFO_CHAT_ID,
                    message_id=message_ids_in_chat[task_number],
                    parse_mode="Markdown"
                )
            else:
                bot.edit_message_text(
                    task_message, chat_id=INFO_CHAT_ID,
                    message_id=message_ids_in_chat[task_number],
                    parse_mode="Markdown"
                )
        else:
            if task_info.get('photo'):
                sent_message = bot.send_photo(
                    INFO_CHAT_ID, photo=task_info['photo'], caption=task_message, parse_mode="Markdown"
                )
            else:
                sent_message = bot.send_message(INFO_CHAT_ID, task_message, parse_mode="Markdown")
            message_ids_in_chat[task_number] = sent_message.message_id
    except Exception as e:
        logger.error(f"Ошибка при обновлении статуса задачи: {e}")

def close_task_topic(thread_id):
    """Закрывает тему задачи."""
    try:
        bot.close_forum_topic(chat_id=INFO_CHAT_ID, message_thread_id=thread_id)
    except Exception as e:
        logger.error(f"Ошибка при закрытии темы: {e}")

def create_buttons(skip_photo=False):
    """Создаёт вертикальные кнопки с вариантами ответов."""
    keyboard = types.InlineKeyboardMarkup()
    if skip_photo:
        skip_button = types.InlineKeyboardButton(text="Пропустить", callback_data="skip_photo")
        keyboard.add(skip_button)
    else:
        buttons = [
            types.InlineKeyboardButton(text="Беру задачу", callback_data="take"),
            types.InlineKeyboardButton(text="Не имею компетенции", callback_data="no_competence"),
            types.InlineKeyboardButton(text="Не могу взять", callback_data="cant_take")
        ]
        for button in buttons:
            keyboard.add(button)  # Добавляем кнопки в столбик
    return keyboard

@bot.message_handler(commands=['start'])
def start_message(message):
    """Начальное сообщение с кнопками для отправителя."""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    start_button = types.KeyboardButton("Создать задачу")
    keyboard.add(start_button)
    bot.send_message(message.chat.id, "Привет! Нажмите кнопку, чтобы начать создание задачи.", reply_markup=keyboard)

@bot.message_handler(func=lambda message: message.text == "Создать задачу")
def create_task(message):
    """Начинает процесс создания задачи."""
    bot.send_message(message.chat.id, "Отправьте тему задачи.")
    pending_tasks[message.chat.id] = {'topic': None, 'description': None, 'photo': None}

@bot.message_handler(content_types=['text', 'photo'])
def handle_message(message):
    global task_counter, pending_tasks, task_status

    if message.from_user.id == SENDER_USER_ID:
        if message.chat.id in pending_tasks:
            task_data = pending_tasks[message.chat.id]

            # Сохраняем тему задачи
            if task_data['topic'] is None:
                task_data['topic'] = message.text
                bot.send_message(message.chat.id, "Теперь отправьте описание задачи.")
                return

            # Сохраняем описание задачи
            if task_data['description'] is None:
                task_data['description'] = message.text
                bot.send_message(message.chat.id, "Теперь отправьте фото задачи (или пропустите).", reply_markup=create_buttons(skip_photo=True))
                return

            # Сохраняем фото или пропускаем шаг
            if message.photo:
                task_data['photo'] = message.photo[-1].file_id

            task_status[task_counter] = {
                'topic': task_data['topic'],
                'description': task_data['description'],
                'photo': task_data.get('photo'),
                'status': {}
            }

            # Создаём тему форума
            thread_id = create_forum_topic(task_counter, task_data['topic'][:20])  # Используем только первые 20 символов для краткости

            if thread_id is not None:
                task_message = (
                    f"*Задача #{task_counter}*\n"
                    f"📌 {task_data['topic']}\n"
                    f"📝 {task_data['description']}\n"
                )

                # Отправляем сообщение получателю
                if task_data['photo']:
                    bot.send_photo(RECEIVER_USER_ID, photo=task_data['photo'], caption=task_message, reply_markup=create_buttons())
                else:
                    bot.send_message(RECEIVER_USER_ID, task_message, reply_markup=create_buttons())

                # Отправляем сообщение в тред форума
                send_message_to_forum_thread(task_message, thread_id, photo=task_data['photo'])

                # Обновляем статус в общем чате
                send_task_status_update(task_counter)

                # Сохраняем ID треда
                created_threads[task_counter] = thread_id

                task_counter += 1

            # Завершаем процесс создания задачи
            pending_tasks.pop(message.chat.id)

@bot.message_handler(func=lambda message: message.chat.id == INFO_CHAT_ID)
def ignore_general_chat(message):
    """Игнорирует сообщения в общем чате, не связанные с задачами."""


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    global task_status

    if call.from_user.id == RECEIVER_USER_ID:
        try:
            full_name = get_full_name(call.from_user)
            task_number = task_counter - 1

            if call.data == "take":
                response = "Вы взяли задачу!"
                status = "готов взять задачу"
            elif call.data == "no_competence":
                response = "Вы не имеете компетенции для этой задачи."
                status = "не готов взять задачу"
            elif call.data == "cant_take":
                response = "Вы не можете взять задачу."
                status = "не может взять задачу"
            elif call.data == "skip_photo":
                bot.send_message(call.message.chat.id, "Шаг с добавлением фото пропущен. Завершите задачу.")
                return

            bot.answer_callback_query(call.id, response)

            task_status[task_number]['status'][full_name] = status

            # Отключаем кнопки
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)

            # Обновляем статус задачи в общем чате
            send_task_status_update(task_number)

        except Exception as e:
            logger.error(f"Ошибка при обработке callback: {e}")

if __name__ == '__main__':
    bot.polling(none_stop=True, interval=0)
