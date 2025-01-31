import json
import logging
from datetime import datetime, timedelta
from telebot import TeleBot, types
from apscheduler.schedulers.background import BackgroundScheduler
from config import TOKEN, SENDER_USER_IDS, RECEIVER_USER_IDS, INFO_CHAT_ID

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot = TeleBot(TOKEN)
scheduler = BackgroundScheduler()
scheduler.start()

# Константы
TASK_FIELDS = [
    ('client_name', "Название клиента"),
    ('urgency', "Срочность задачи"),
    ('what_to_do', "Что нужно сделать"),
    ('goal', "Цель работы"),
    ('client_pp', "ПП клиента"),
    ('equipment', "Оборудование (марка, модель)"),
    ('cost_and_hours', "Сумма и количество часов"),
    ('contact_person', "Контактное лицо (ФИО и номера)"),
    ('photo', "Фото задачи (или пропустите)")
]

STATUS_MAP = {
    'take': 'готов взять задачу',
    'no_competence': 'не имеет компетенций',
    'cant_take': 'не может взять задачу'
}

ICON_COLOR = 7322096
MAX_TOPIC_LENGTH = 20

class TaskManager:
    def __init__(self):
        self.tasks = {}
        self.pending_tasks = {}
        self.threads = {}
        self.message_ids = {}
        self.scheduled_jobs = {}  # task_number: job_id
        self._load_state()

    def _load_state(self):
        try:
            with open('task_state.json', 'r') as f:
                data = json.load(f)
                self.task_counter = data.get('task_counter', 1)
        except FileNotFoundError:
            self.task_counter = 1
        except Exception as e:
            logger.error(f"Error loading state: {e}")
            self.task_counter = 1

    def save_state(self):
        data = {
            'task_counter': self.task_counter
        }
        try:
            with open('task_state.json', 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logger.error(f"Error saving state: {e}")

    def create_task(self, chat_id):
        self.pending_tasks[chat_id] = {field: None for field, _ in TASK_FIELDS}
        return self.pending_tasks[chat_id]

    def get_next_field(self, task_data):
        for field, _ in TASK_FIELDS:
            if task_data[field] is None:
                return field
        return None

task_manager = TaskManager()

def send_reminder_to_user(task_number, user_id):
    try:
        bot.send_message(
            user_id,
            f"⏰ Напоминание! Пожалуйста, ответьте на задачу #{task_number}.",
            reply_markup=None
        )
    except Exception as e:
        logger.error(f"Error sending reminder to user {user_id}: {e}")

def send_unanswered_notification(task_number):
    if task_number in task_manager.tasks:
        task_data = task_manager.tasks[task_number]
        # Получаем список пользователей, которые еще не ответили
        users_to_remind = [
            user_id for user_id in RECEIVER_USER_IDS
            if user_id not in task_data.get('responded_users', [])
        ]
        
        if users_to_remind:
            # Получаем имена пользователей, которые не ответили
            unanswered_users = []
            for user_id in users_to_remind:
                try:
                    user = bot.get_chat_member(INFO_CHAT_ID, user_id).user
                    # Формируем имя пользователя: имя + фамилия (если есть) + username (если есть)
                    user_name = f"{user.first_name} {user.last_name}" if user.last_name else user.first_name
                    if user.username:
                        user_name += f" (@{user.username})"
                    unanswered_users.append(user_name)
                except Exception as e:
                    logger.error(f"Error getting user info: {e}")
            
            if unanswered_users:
                message = (
                         f"@nnthruslpn\n"
                         f"Следующие специалисты не дали ответ на задачу #{task_number} в течение 2 минут:\n"
                         f"{', '.join(unanswered_users)}"
)
                bot.send_message(INFO_CHAT_ID, message)

def create_keyboard(buttons, row_width=1):
    keyboard = types.InlineKeyboardMarkup(row_width=row_width)
    for btn in buttons:
        if isinstance(btn, list):
            keyboard.add(*[types.InlineKeyboardButton(text, callback_data=data) for text, data in btn])
        else:
            keyboard.add(types.InlineKeyboardButton(btn[0], callback_data=btn[1]))
    return keyboard

def main_task_keyboard(task_number):
    return create_keyboard([
        [("Беру задачу", f"take:{task_number}")],
        [("Не имею компетенции", f"no_competence:{task_number}")],
        [("Не могу взять", f"cant_take:{task_number}")]
    ])

def skip_step_keyboard():
    return create_keyboard([("Пропустить шаг", "skip_step")])

def generate_task_message(task_number, task_data, with_status=True):
    message = [
        f"*Задача #{task_number}*",
        f"📌 Название клиента: {task_data['client_name']}",
        f"⚠️ Срочность: {task_data['urgency']}",
        f"📝 Что нужно сделать: {task_data['what_to_do']}",
        f"🎯 Цель работы: {task_data['goal']}",
        f"📄 ПП клиента: {task_data['client_pp']}",
        f"⚙️ Оборудование: {task_data['equipment']}",
        f"💰 Сумма и часы: {task_data['cost_and_hours']}",
        f"📞 Контактные лица: {task_data['contact_person']}",
    ]
    
    if with_status and task_data.get('status'):
        message.append("Статусы:\n" + "\n".join(
            f"{idx}. {user} — {status}" 
            for idx, (user, status) in enumerate(task_data['status'].items(), 1)
        ))
    
    return "\n".join(message)

def handle_media_message(message, task_data):
    if message.content_type == 'photo':
        return message.photo[-1].file_id
    return message.text if message.content_type == 'text' else None

def update_task_status(task_number):
    task_data = task_manager.tasks[task_number]
    message = generate_task_message(task_number, task_data)
    
    try:
        if task_number in task_manager.message_ids:
            method = bot.edit_message_caption if task_data.get('photo') else bot.edit_message_text
            method(message, INFO_CHAT_ID, task_manager.message_ids[task_number], parse_mode="Markdown")
        else:
            if task_data.get('photo'):
                sent = bot.send_photo(INFO_CHAT_ID, task_data['photo'], caption=message, parse_mode="Markdown")
            else:
                sent = bot.send_message(INFO_CHAT_ID, message, parse_mode="Markdown")
            task_manager.message_ids[task_number] = sent.message_id
    except Exception as e:
        logger.error(f"Error updating task status: {e}")

@bot.message_handler(commands=['start'])
def start_handler(message):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    keyboard.add(types.KeyboardButton("Создать задачу"))
    bot.send_message(message.chat.id, "Привет! Нажмите кнопку, чтобы начать создание задачи.", reply_markup=keyboard)

@bot.message_handler(func=lambda m: m.text == "Создать задачу" and m.from_user.id in SENDER_USER_IDS)
def task_creation_handler(message):
    task = task_manager.create_task(message.chat.id)
    bot.send_message(message.chat.id, "Отправьте название клиента.")

@bot.message_handler(content_types=['text', 'photo'], func=lambda m: m.from_user.id in SENDER_USER_IDS)
def process_task_data(message):
    chat_id = message.chat.id
    if chat_id not in task_manager.pending_tasks:
        return

    task_data = task_manager.pending_tasks[chat_id]
    current_field = task_manager.get_next_field(task_data)
    
    if not current_field:
        return

    task_data[current_field] = handle_media_message(message, task_data)
    next_field = task_manager.get_next_field(task_data)

    if next_field:
        prompt = TASK_FIELDS[[f[0] for f in TASK_FIELDS].index(next_field)][1]
        reply_markup = skip_step_keyboard() if next_field == 'photo' else None
        bot.send_message(chat_id, f"Теперь отправьте {prompt}.", reply_markup=reply_markup)
    else:
        finalize_task(chat_id, task_data)

def finalize_task(chat_id, task_data):
    task_number = task_manager.task_counter
    task_data['status'] = {}
    task_manager.tasks[task_number] = task_data
    
    try:
        thread_id = bot.create_forum_topic(
            INFO_CHAT_ID, 
            f"{task_number}. {task_data['client_name'][:MAX_TOPIC_LENGTH]}", 
            icon_color=ICON_COLOR
        ).message_thread_id
        
        message = generate_task_message(task_number, task_data, with_status=False)
        if task_data['photo']:
            for receiver_id in RECEIVER_USER_IDS:
                bot.send_photo(receiver_id, task_data['photo'], message, 
                             reply_markup=main_task_keyboard(task_number))
            send_to_thread = lambda: bot.send_photo(INFO_CHAT_ID, task_data['photo'], message, 
                                                  message_thread_id=thread_id)
        else:
            for receiver_id in RECEIVER_USER_IDS:
                bot.send_message(receiver_id, message, 
                               reply_markup=main_task_keyboard(task_number))
            send_to_thread = lambda: bot.send_message(INFO_CHAT_ID, message, 
                                                    message_thread_id=thread_id)
        
        send_to_thread()
        update_task_status(task_number)
        task_manager.threads[task_number] = thread_id
        
        # Schedule reminders
        for receiver_id in RECEIVER_USER_IDS:
            scheduler.add_job(
                send_reminder_to_user,
                'date',
                run_date=datetime.now() + timedelta(minutes=1),  # Напоминание через 1 минуту
                args=[task_number, receiver_id]
            )
        
        # Schedule general notification
        scheduler.add_job(
            send_unanswered_notification,
            'date',
            run_date=datetime.now() + timedelta(minutes=2),  # Уведомление в общий чат через 2 минуты
            args=[task_number]
        )
        
        task_manager.task_counter += 1
        task_manager.save_state()
        del task_manager.pending_tasks[chat_id]
    except Exception as e:
        logger.error(f"Error finalizing task: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith(('take', 'no_competence', 'cant_take', 'skip')))
def callback_handler(call):
    try:
        if call.data == "skip_step":
            handle_skip_step(call)
        else:
            handle_task_action(call)
    except Exception as e:
        logger.error(f"Callback error: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка при обработке запроса")

def handle_skip_step(call):
    chat_id = call.message.chat.id
    if chat_id in task_manager.pending_tasks:
        task_data = task_manager.pending_tasks[chat_id]
        task_data['photo'] = None
        finalize_task(chat_id, task_data)
        bot.answer_callback_query(call.id, "Шаг с фото пропущен")
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)

def handle_task_action(call):
    action, task_number = call.data.split(':', 1)
    task_number = int(task_number)
    
    if task_number not in task_manager.tasks:
        return

    user_id = call.from_user.id
    user_name = f"{call.from_user.first_name} {call.from_user.last_name}" if call.from_user.last_name else call.from_user.first_name
    status = STATUS_MAP.get(action)
    
    if status:
        # Добавляем пользователя в список ответивших
        if 'responded_users' not in task_manager.tasks[task_number]:
            task_manager.tasks[task_number]['responded_users'] = []
        if user_id not in task_manager.tasks[task_number]['responded_users']:
            task_manager.tasks[task_number]['responded_users'].append(user_id)
        
        # Обновляем статус задачи
        task_manager.tasks[task_number]['status'][user_name] = status
        update_task_status(task_number)
        
        bot.answer_callback_query(call.id, f"Статус обновлен: {status}")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)

if __name__ == '__main__':
    logger.info("Starting bot...")
    try:
        bot.polling(none_stop=True)
    except KeyboardInterrupt:
        scheduler.shutdown()
        logger.info("Bot stopped")