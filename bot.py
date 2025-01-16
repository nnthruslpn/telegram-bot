import logging
from telebot import TeleBot, types
from config import TOKEN, SENDER_USER_ID, RECEIVER_USER_ID, INFO_CHAT_ID

bot = TeleBot(TOKEN)
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

task_counter, task_status, created_threads, message_ids_in_chat, pending_tasks = 1, {}, {}, {}, {}

def get_full_name(user): 
    return f"{user.first_name} {user.last_name}" if user.last_name else user.first_name

def create_forum_topic(task_number, short_topic): 
    try: 
        return bot.create_forum_topic(INFO_CHAT_ID, f"{task_number}. {short_topic[:20]}", icon_color=7322096).message_thread_id
    except Exception as e: 
        logger.error(f"Error creating topic: {e}")

def send_message_to_forum_thread(message, thread_id, photo=None): 
    try:
        if photo:
            bot.send_photo(INFO_CHAT_ID, photo=photo, caption=message, message_thread_id=thread_id)
        else:
            bot.send_message(INFO_CHAT_ID, text=message, message_thread_id=thread_id)
    except Exception as e: 
        logger.error(f"Error sending message to thread: {e}")

def send_task_status_update(task_number): 
    task_info = task_status[task_number]
    
    # Формируем сообщение с учетом новых полей
    task_message = f"*Задача #{task_number}*\n" \
                   f"📌 Вид работ: {task_info['work_type']}\n" \
                   f"⚠️ Срочность: {task_info['urgency']}\n" \
                   f"📝 Что нужно сделать: {task_info['what_to_do']}\n" \
                   f"🎯 Цель работы: {task_info['goal']}\n" \
                   f"📄 ПП клиента: {task_info['client_pp']}\n" \
                   f"⚙️ Оборудование: {task_info['equipment']}\n" \
                   f"💰 Сумма и часы: {task_info['cost_and_hours']}\n" \
                   f"📞 Контактные лица: {task_info['contact_person']}\n" \
                   f"Статусы:\n"
    
    # Добавляем статусы участников
    task_message += "\n".join([f"{idx}. {user} — {status}" 
                               for idx, (user, status) in enumerate(task_info['status'].items(), 1)])

    try:
        # Обновляем сообщение в чате с учетом новых данных
        if task_number in message_ids_in_chat:
            method = bot.edit_message_caption if task_info.get('photo') else bot.edit_message_text
            method(task_message, chat_id=INFO_CHAT_ID, message_id=message_ids_in_chat[task_number], parse_mode="Markdown")
        else:
            sent_message = bot.send_photo(INFO_CHAT_ID, photo=task_info['photo'], caption=task_message, parse_mode="Markdown") if task_info.get('photo') else bot.send_message(INFO_CHAT_ID, task_message, parse_mode="Markdown")
            message_ids_in_chat[task_number] = sent_message.message_id
    except Exception as e:
        logger.error(f"Error updating task status: {e}")

def create_buttons(skip_photo=False): 
    keyboard = types.InlineKeyboardMarkup()
    buttons = [types.InlineKeyboardButton(text="Пропустить шаг", callback_data="skip_step")] if skip_photo else [
        types.InlineKeyboardButton(text="Беру задачу", callback_data="take"),
        types.InlineKeyboardButton(text="Не имею компетенции", callback_data="no_competence"),
        types.InlineKeyboardButton(text="Не могу взять", callback_data="cant_take")
    ]
    [keyboard.add(button) for button in buttons]
    return keyboard

@bot.message_handler(commands=['start'])
def start_message(message):
    """Начальное сообщение с кнопкой для отправителя."""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    start_button = types.KeyboardButton("Создать задачу")
    keyboard.add(start_button)
    bot.send_message(
        message.chat.id, 
        "Привет! Нажмите кнопку, чтобы начать создание задачи.", 
        reply_markup=keyboard
    )

@bot.message_handler(func=lambda message: message.text == "Создать задачу")
def create_task(message): 
    pending_tasks[message.chat.id] = {
        'work_type': None,
        'urgency': None,
        'what_to_do': None,
        'goal': None,
        'client_pp': None,
        'equipment': None,
        'cost_and_hours': None,
        'contact_person': None,
        'photo': None
    }
    bot.send_message(message.chat.id, "Отправьте вид работ.")

@bot.message_handler(content_types=['text', 'photo'])

def handle_message(message):
    global task_counter
    if message.from_user.id == SENDER_USER_ID and message.chat.id in pending_tasks:
        task_data = pending_tasks[message.chat.id]

        if task_data['work_type'] is None:
            task_data['work_type'] = message.text
            bot.send_message(message.chat.id, "Теперь отправьте срочность задачи.")
        elif task_data['urgency'] is None:
            task_data['urgency'] = message.text
            bot.send_message(message.chat.id, "Теперь отправьте описание, что нужно сделать.")
        elif task_data['what_to_do'] is None:
            task_data['what_to_do'] = message.text
            bot.send_message(message.chat.id, "Теперь отправьте цель работы.")
        elif task_data['goal'] is None:
            task_data['goal'] = message.text
            bot.send_message(message.chat.id, "Теперь отправьте ПП клиента.")
        elif task_data['client_pp'] is None:
            task_data['client_pp'] = message.text
            bot.send_message(message.chat.id, "Теперь отправьте информацию об оборудовании (марка, модель).")
        elif task_data['equipment'] is None:
            task_data['equipment'] = message.text
            bot.send_message(message.chat.id, "Теперь отправьте сумму и количество часов.")
        elif task_data['cost_and_hours'] is None:
            task_data['cost_and_hours'] = message.text
            bot.send_message(message.chat.id, "Теперь отправьте контактное лицо (ФИО и номера).")
        elif task_data['contact_person'] is None:
            task_data['contact_person'] = message.text
            bot.send_message(message.chat.id, "Теперь отправьте фото задачи (или пропустите).", reply_markup=create_buttons(skip_photo=True))
        else:
            task_data['photo'] = message.photo[-1].file_id if message.photo else None
            task_status[task_counter] = {**task_data, 'status': {}}
            thread_id = create_forum_topic(task_counter, task_data['work_type'])
            if thread_id:
                task_message = f"*Задача #{task_counter}*\n" \
                               f"📌 Вид работ: {task_data['work_type']}\n" \
                               f"⚠️ Срочность: {task_data['urgency']}\n" \
                               f"📝 Что нужно сделать: {task_data['what_to_do']}\n" \
                               f"🎯 Цель работы: {task_data['goal']}\n" \
                               f"📄 ПП клиента: {task_data['client_pp']}\n" \
                               f"⚙️ Оборудование: {task_data['equipment']}\n" \
                               f"💰 Сумма и часы: {task_data['cost_and_hours']}\n" \
                               f"📞 Контактные лица: {task_data['contact_person']}\n"
                bot.send_message(RECEIVER_USER_ID, task_message, reply_markup=create_buttons()) if not task_data['photo'] else bot.send_photo(RECEIVER_USER_ID, task_data['photo'], caption=task_message, reply_markup=create_buttons())
                send_message_to_forum_thread(task_message, thread_id, photo=task_data['photo'])
                send_task_status_update(task_counter)
                created_threads[task_counter] = thread_id
                task_counter += 1
            pending_tasks.pop(message.chat.id)

@bot.message_handler(func=lambda message: message.chat.id == INFO_CHAT_ID)
def ignore_general_chat(message): pass

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    global task_counter
    if call.from_user.id == RECEIVER_USER_ID or call.data == "skip_step":
        try:
            task_number = task_counter if call.data == "skip_step" else task_counter - 1
            full_name = get_full_name(call.from_user)
            if call.data == "skip_step":
                task_data = pending_tasks.get(call.message.chat.id)
                if task_data:
                    task_status[task_number] = {**task_data, 'status': {}}
                    thread_id = create_forum_topic(task_number, task_data['work_type'])
                    if thread_id:
                        task_message = f"*Задача #{task_number}*\n" \
                                       f"📌 Вид работ: {task_data['work_type']}\n" \
                                       f"⚠️ Срочность: {task_data['urgency']}\n" \
                                       f"📝 Что нужно сделать: {task_data['what_to_do']}\n" \
                                       f"🎯 Цель работы: {task_data['goal']}\n" \
                                       f"📄 ПП клиента: {task_data['client_pp']}\n" \
                                       f"⚙️ Оборудование: {task_data['equipment']}\n" \
                                       f"💰 Сумма и часы: {task_data['cost_and_hours']}\n" \
                                       f"📞 Контактные лица: {task_data['contact_person']}\n"
                        bot.send_message(RECEIVER_USER_ID, task_message, reply_markup=create_buttons())
                        send_message_to_forum_thread(task_message, thread_id)
                        send_task_status_update(task_number)
                        created_threads[task_number] = thread_id
                        task_counter += 1
                    pending_tasks.pop(call.message.chat.id)
                bot.answer_callback_query(call.id, "Шаг пропущен. Переход к следующему шагу.")
                return

            status = {"take": "готов взять задачу", "no_competence": "не имеет компетенций", "cant_take": "не может взять задачу"}.get(call.data)
            bot.answer_callback_query(call.id, f"Вы {status}! Ваша заявка принята.")
            task_status[task_number]['status'][full_name] = status
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            send_task_status_update(task_number)
        except Exception as e:
            logger.error(f"Error handling callback: {e}")

if __name__ == '__main__':
    bot.polling(none_stop=True, interval=0)
