import json
import logging
from datetime import datetime, timedelta
from telebot import TeleBot, types
from apscheduler.schedulers.background import BackgroundScheduler
from config import SENDER_USER_IDS, RECEIVER_USER_IDS, INFO_CHAT_ID
import os
from dotenv import load_dotenv
load_dotenv()
TOKEN = os.getenv("TOKEN")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot = TeleBot(TOKEN)
scheduler = BackgroundScheduler()
scheduler.start()

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
    'no_competence': 'не уверен, нужны уточнения',
    'cant_take': 'не может взять задачу'
}

ICON_COLOR = 7322096
MAX_TOPIC_LENGTH = 20


class TaskManager:
    def __init__(self):
        self.tasks = {}
        self.pending_tasks = {}
        self.threads = {}  # Хранит task_number: thread_id
        self.message_ids = {}  # Хранит task_number: message_id
        self._load_state()

    def _load_state(self):
        try:
            with open('task_state.json', 'r') as f:
                data = json.load(f)
                self.task_counter = data.get('task_counter', 1)
                self.tasks = {int(k): v for k, v in data.get(
                    'tasks', {}).items()}
                self.threads = {int(k): v for k, v in data.get(
                    'threads', {}).items()}
                self.message_ids = {int(k): v for k, v in data.get(
                    'message_ids', {}).items()}
                self.pending_tasks = {int(k): v for k, v in data.get(
                    'pending_tasks', {}).items()}

                logger.info(
                    f"State loaded successfully. Tasks: {len(self.tasks)}, Threads: {len(self.threads)}, Messages: {len(self.message_ids)}")

        except FileNotFoundError:
            logger.info("State file not found. Starting fresh.")
            self.task_counter = 1
        except Exception as e:
            logger.error(f"Error loading state: {e}")
            self.task_counter = 1

    def update_forum_message(self, task_number):
        task_data = self.tasks[task_number]
        try:
            thread_id = self.threads[task_number]
            message_id = self.message_ids[task_number]
            
            if task_data.get('photo'):
                bot.edit_message_caption(
                    chat_id=INFO_CHAT_ID,
                    message_id=message_id,
                    caption=self.generate_task_message(task_number, task_data, with_status=True),
                    parse_mode="Markdown",
                    reply_markup=self.generate_task_controls(task_number, task_data['is_resolved'])
                )
            else:
                bot.edit_message_text(
                    chat_id=INFO_CHAT_ID,
                    message_id=message_id,
                    text=self.generate_task_message(task_number, task_data, with_status=True),
                    parse_mode="Markdown",
                    reply_markup=self.generate_task_controls(task_number, task_data['is_resolved'])
                )
        except Exception as e:
            logger.error(f"Error updating forum message: {e}")

    def update_main_chat_status(self, task_number):
        task_data = self.tasks[task_number]
        try:
            if 'main_chat_message_id' in task_data:
                if task_data.get('photo'):
                    bot.edit_message_caption(
                        chat_id=INFO_CHAT_ID,
                        message_id=task_data['main_chat_message_id'],
                        caption=self.generate_task_message(task_number, task_data, with_status=True),
                        parse_mode="Markdown"
                    )
                else:
                    bot.edit_message_text(
                        chat_id=INFO_CHAT_ID,
                        message_id=task_data['main_chat_message_id'],
                        text=self.generate_task_message(task_number, task_data, with_status=True),
                        parse_mode="Markdown"
                    )
        except Exception as e:
            logger.error(f"Error updating main chat: {e}")

    def save_state(self):
        data = {
            'task_counter': self.task_counter,
            'tasks': self.tasks,
            'threads': self.threads,
            'message_ids': self.message_ids,
            'pending_tasks': self.pending_tasks
        }
        try:
            with open('task_state.json', 'w') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            logger.info("State saved successfully.")
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

    def finalize_task(self, chat_id, task_data):
        try:
            user = bot.get_chat(chat_id)
            sender_name = f"{user.first_name}"
            if user.last_name:
                sender_name += f" {user.last_name}"
        except Exception as e:
            logger.error(f"Error getting sender info: {e}")
            sender_name = "Неизвестный отправитель"

        task_number = self.task_counter
        task_data.update({
            'sender_name': sender_name,
            'status': {},
            'responded_users': [],
            'is_resolved': False,
            'sender_id': chat_id
        })
        
        self.tasks[task_number] = task_data
        self.task_counter += 1

        try:
            # Отправка в основной чат
            if task_data.get('photo'):
                main_msg = bot.send_photo(
                    INFO_CHAT_ID,
                    task_data['photo'],
                    caption=self.generate_task_message(task_number, task_data, with_status=False),
                    parse_mode="Markdown"
                )
            else:
                main_msg = bot.send_message(
                    INFO_CHAT_ID,
                    self.generate_task_message(task_number, task_data, with_status=False),
                    parse_mode="Markdown"
                )
            task_data['main_chat_message_id'] = main_msg.message_id

            # Создание форум топика
            topic_name = f"🔴 {task_number} {task_data['client_name'][:MAX_TOPIC_LENGTH]}"
            forum_topic = bot.create_forum_topic(
                INFO_CHAT_ID, 
                topic_name, 
                icon_color=ICON_COLOR
            )
            thread_id = forum_topic.message_thread_id

            # Отправка в форум
            if task_data.get('photo'):
                forum_msg = bot.send_photo(
                    INFO_CHAT_ID,
                    task_data['photo'],
                    caption=self.generate_task_message(task_number, task_data, with_status=False),
                    parse_mode="Markdown",
                    message_thread_id=thread_id,
                    reply_markup=self.generate_task_controls(task_number, False)
                )
            else:
                forum_msg = bot.send_message(
                    INFO_CHAT_ID,
                    self.generate_task_message(task_number, task_data, with_status=False),
                    parse_mode="Markdown",
                    message_thread_id=thread_id,
                    reply_markup=self.generate_task_controls(task_number, False)
                )

            self.threads[task_number] = thread_id
            self.message_ids[task_number] = forum_msg.message_id

            # Отправка получателям
            for receiver_id in RECEIVER_USER_IDS:
                try:
                    if task_data.get('photo'):
                        bot.send_photo(
                            receiver_id,
                            task_data['photo'],
                            caption=self.generate_task_message(task_number, task_data, with_status=False),
                            parse_mode="Markdown",
                            reply_markup=self.main_task_keyboard(task_number)
                        )
                    else:
                        bot.send_message(
                            receiver_id, 
                            self.generate_task_message(task_number, task_data, with_status=False),
                            parse_mode="Markdown",
                            reply_markup=self.main_task_keyboard(task_number)
                        )
                    scheduler.add_job(
                        send_reminder_to_user,
                        'date',
                        run_date=datetime.now() + timedelta(minutes=30),
                        args=[task_number, receiver_id]
                    )
                except Exception as e:
                    logger.error(f"Error sending to user {receiver_id}: {e}")

            scheduler.add_job(
                send_unanswered_notification,
                'date',
                run_date=datetime.now() + timedelta(minutes=60),
                args=[task_number]
            )

            del self.pending_tasks[chat_id]
            self.save_state()

            bot.send_message(
                chat_id,
                f"✅ Задача #{task_number} успешно создана!",
                reply_markup=types.ReplyKeyboardRemove()
            )

        except Exception as e:
            logger.error(f"Error finalizing task: {e}")
            bot.send_message(chat_id, "❌ Ошибка при создании задачи.")
            self.save_state()

    def generate_task_message(self, task_number, task_data, with_status=True):
        message = [
            f"*Задача #{task_number}*",
            f"👤 Отправитель: {task_data['sender_name']}",
            f"📌 Клиент: {task_data['client_name']}",
            f"⚠️ Срочность: {task_data['urgency']}",
            f"📝 Задача: {task_data['what_to_do']}",
            f"🎯 Цель: {task_data['goal']}",
            f"📄 ПП клиента: {task_data['client_pp']}",
            f"⚙️ Оборудование: {task_data['equipment']}",
            f"💰 Сумма/часы: {task_data['cost_and_hours']}",
            f"📞 Контакты: {task_data['contact_person']}",
        ]

        if with_status and task_data.get('status'):
            message.append("\n*Статусы ответов:*")
            message.extend(
                f"• {user} — {status}"
                for user, status in task_data['status'].items()
            )

        return "\n".join(message)

    def main_task_keyboard(self, task_number):
        return self.create_keyboard([
            [("Беру задачу", f"user_take:{task_number}")],
            [("Не уверен, нужны уточнения",
              f"user_no_competence:{task_number}")],
            [("Не могу взять", f"user_cant_take:{task_number}")]
        ])

    def generate_task_controls(self, task_number, is_resolved):
        if is_resolved:
            return self.create_keyboard([[("🔴 Вернуть в работу", f"forum_reopen:{task_number}")]])
        return self.create_keyboard([
            [("🟢 Решено", f"forum_resolve:{task_number}")],
            [("🟡 Взять в работу", f"forum_take:{task_number}")]
        ])

    @staticmethod
    def create_keyboard(buttons, row_width=1):
        keyboard = types.InlineKeyboardMarkup(row_width=row_width)
        for btn in buttons:
            if isinstance(btn, list):
                keyboard.add(
                    *[types.InlineKeyboardButton(text, callback_data=data) for text, data in btn])
            else:
                keyboard.add(types.InlineKeyboardButton(
                    btn[0], callback_data=btn[1]))
        return keyboard


task_manager = TaskManager()


def send_reminder_to_user(task_number, user_id):
    if task_number not in task_manager.tasks:
        return

    task_data = task_manager.tasks[task_number]
    if user_id in task_data.get('responded_users', []):
        return

    try:
        bot.send_message(
            user_id,
            f"⏰ Напоминание! Пожалуйста, ответьте на задачу #{task_number}.",
        )
    except Exception as e:
        logger.error(f"Error sending reminder to user {user_id}: {e}")


def send_unanswered_notification(task_number):
    if task_number not in task_manager.tasks:
        return

    task_data = task_manager.tasks[task_number]
    users_to_remind = [
        user_id for user_id in RECEIVER_USER_IDS
        if user_id not in task_data.get('responded_users', [])
    ]

    if not users_to_remind:
        return

    unanswered_users = []
    for user_id in users_to_remind:
        try:
            user = bot.get_chat_member(INFO_CHAT_ID, user_id).user
            user_name = f"{user.first_name} {user.last_name}" if user.last_name else user.first_name
            if user.username:
                user_name += f" (@{user.username})"
            unanswered_users.append(user_name)
        except Exception as e:
            logger.error(f"Error getting user info: {e}")

    if unanswered_users:
        message = (
            f"@aagutenev\n"
            f"Следующие специалисты не дали ответ на задачу #{task_number} в течение часа:\n"
            f"{', '.join(unanswered_users)}"
        )
        bot.send_message(INFO_CHAT_ID, message)


def skip_step_keyboard():
    return task_manager.create_keyboard([("Пропустить шаг", "skip_step")])






def handle_media_message(message, task_data):
    if message.content_type == 'photo':
        return message.photo[-1].file_id
    return message.text if message.content_type == 'text' else None


@bot.message_handler(commands=['start'], chat_types=['private'])
def start_handler(message):
    if message.from_user.id in SENDER_USER_IDS:
        keyboard = types.ReplyKeyboardMarkup(
            resize_keyboard=True, one_time_keyboard=True)
        keyboard.add(types.KeyboardButton("Создать задачу"))
        bot.send_message(message.chat.id,
                         "Привет! Нажмите кнопку, чтобы начать создание задачи.",
                         reply_markup=keyboard)
    else:
        bot.send_message(message.chat.id,
                         "Добро пожаловать! Здесь вы можете получать и принимать задачи.",
                         reply_markup=types.ReplyKeyboardRemove())


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
        bot.send_message(
            chat_id, f"Теперь отправьте {prompt}.", reply_markup=reply_markup)
    else:
        task_manager.finalize_task(chat_id, task_data)


@bot.callback_query_handler(func=lambda call: call.data.startswith(('forum_', 'user_', 'skip')))
def callback_handler(call):
    try:
        if call.data == "skip_step":
            handle_skip_step(call)
            return

        parts = call.data.split(':', 1)
        prefix_action = parts[0]
        task_number = int(parts[1]) if len(parts) > 1 else None

        if prefix_action.startswith('forum_'):
            action = prefix_action.split('_', 1)[1]
            handle_forum_action(call, action, task_number)
        elif prefix_action.startswith('user_'):
            action = prefix_action.split('_', 1)[1]
            handle_user_response(call, action, task_number)

    except Exception as e:
        logger.error(f"Callback error: {e}")
        bot.answer_callback_query(call.id, "Ошибка обработки запроса")


def handle_skip_step(call):
    chat_id = call.message.chat.id
    if chat_id in task_manager.pending_tasks:
        task_data = task_manager.pending_tasks[chat_id]
        task_data['photo'] = None
        task_manager.finalize_task(chat_id, task_data)
        bot.answer_callback_query(call.id, "Шаг с фото пропущен")
        bot.edit_message_reply_markup(
            chat_id, call.message.message_id, reply_markup=None)


def handle_forum_action(call, action, task_number):
    task_data = task_manager.tasks.get(task_number)
    if not task_data:
        return bot.answer_callback_query(call.id, "Задача не найдена!")

    thread_id = task_manager.threads.get(task_number)
    if not thread_id:
        return bot.answer_callback_query(call.id, "Ошибка топика!")

    try:
        new_name = ""
        if action == 'resolve':
            if task_data['is_resolved']:
                return bot.answer_callback_query(call.id, "Задача уже решена!")
            new_name = f"🟢 {task_number} {task_data['client_name'][:MAX_TOPIC_LENGTH]}"
            task_data['is_resolved'] = True
            bot.close_forum_topic(INFO_CHAT_ID, thread_id)

        elif action == 'reopen':
            if not task_data['is_resolved']:
                return bot.answer_callback_query(call.id, "Задача уже открыта!")
            new_name = f"🔴 {task_number} {task_data['client_name'][:MAX_TOPIC_LENGTH]}"
            task_data['is_resolved'] = False
            bot.reopen_forum_topic(INFO_CHAT_ID, thread_id)

        elif action == 'take':
            new_name = f"🟡 {task_number} {task_data['client_name'][:MAX_TOPIC_LENGTH]}"
            # Добавляем информацию о взятии задачи
            user_name = call.from_user.first_name
            if call.from_user.last_name:
                user_name += f" {call.from_user.last_name}"
            task_data.setdefault('status', {})[user_name] = STATUS_MAP['take']

        if new_name:
            bot.edit_forum_topic(
                INFO_CHAT_ID,
                thread_id,
                name=new_name
            )

        # Обновляем сообщение с кнопками
        task_manager.update_forum_message(task_number)
        task_manager.save_state()

        bot.answer_callback_query(call.id, "Статус обновлен!")

    except Exception as e:
        logger.error(f"Ошибка изменения темы: {e}")
        bot.answer_callback_query(call.id, f"Ошибка: {str(e)}")


def handle_user_response(call, action, task_number):
    task_data = task_manager.tasks[task_number]
    user_id = call.from_user.id
    user_name = f"{call.from_user.first_name} {call.from_user.last_name}" if call.from_user.last_name else call.from_user.first_name
    status = STATUS_MAP.get(action)

    if status:
        if user_id not in task_data['responded_users']:
            task_data['responded_users'].append(user_id)

        task_data['status'][user_name] = status
        task_manager.update_main_chat_status(task_number)

        try:
            bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=None
            )
            bot.answer_callback_query(call.id, f"Статус обновлен: {status}")
        except Exception as e:
            logger.error(f"Error updating message: {e}")
            bot.answer_callback_query(call.id, "Ошибка обновления!")


if __name__ == '__main__':
    logger.info("Starting bot...")
    try:
        bot.polling(none_stop=True)
    except KeyboardInterrupt:
        scheduler.shutdown()
        task_manager.save_state()
        logger.info("Bot stopped gracefully")