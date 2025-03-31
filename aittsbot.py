import os
import asyncio
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackContext
from TTS.api import TTS
import concurrent.futures
import gc
from queue import Queue
from config import load_config
# from collections import deque  # Закомментируем импорт, так как он нужен только для RateLimiter

# Пытаемся импортировать psutil один раз при запуске
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    print("psutil не установлен. Мониторинг памяти будет недоступен.")

# Загрузка конфигурации
config = load_config()

class AudioTask:
    """Класс для хранения задания на генерацию аудио"""
    def __init__(self, text, update, status_message=None, created_at=None):
        self.text = text
        self.update = update
        self.status_message = status_message
        self.created_at = created_at or datetime.now()

# class RateLimiter:
#     """Класс для контроля частоты запросов"""
#     def __init__(self, max_requests: int, period: timedelta):
#         self.max_requests = max_requests
#         self.period = period
#         self.requests = deque()
#
#     def allow(self) -> bool:
#         now = datetime.now()
#         while self.requests and now - self.requests[0] > self.period:
#             self.requests.popleft()
#         if len(self.requests) < self.max_requests:
#             self.requests.append(now)
#             return True
#         return False

class BotManager:
    def __init__(self):
        self.is_processing = False
        self.tts = None
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.tasks_queue = Queue(maxsize=config.max_queue_size)
        self.queue_processor_running = False
        self.memory_usage_cache = {"value": None, "timestamp": None}
        self.current_task = None
        # self.rate_limiter = RateLimiter(max_requests=10, period=timedelta(seconds=1))

    def initialize_tts(self):
        """Загрузка TTS модели при запуске"""
        try:
            print("Загрузка TTS модели для CPU...")
            
            if not os.path.exists(config.path_default_sempl_voice):
                print(f"ОШИБКА: Файл с голосом {config.path_default_sempl_voice} не найден!")
                raise FileNotFoundError(f"Файл с голосом {config.path_default_sempl_voice} не найден")
            
            gc.collect()
            
            # Минимальная инициализация TTS
            self.tts = TTS(
                model_name="tts_models/multilingual/multi-dataset/xtts_v2",
                progress_bar=False,
                gpu=False
            )
            
            print("TTS модель успешно загружена и готова к использованию")
        except Exception as e:
            print(f"Ошибка инициализации TTS: {e}")
            raise e

    def generate_audio(self, text: str) -> str:
        """Генерация аудиофайла"""
        try:
            os.makedirs("temp_audio", exist_ok=True)
            filename = os.path.join("temp_audio", f"audio_{datetime.now().strftime('%Y%m%d%H%M%S')}.wav")
            
            if len(text) > config.max_text_length:
                text = text[:config.max_text_length]
            
            text = text.replace('\n', ' ').replace('\r', ' ')
            
            print(f"Начало непосредственной генерации текста: {text[:50]}...")
            
            self.tts.tts_to_file(
                text=text,
                file_path=filename,
                speaker_wav=config.path_default_sempl_voice,
                language="ru"
            )
            
            if not os.path.exists(filename) or os.path.getsize(filename) == 0:
                print(f"Ошибка: файл {filename} не создан или пустой")
                return None
            
            return filename
        except Exception as e:
            print(f"Ошибка генерации аудио: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def gen_command(self, update: Update, context: CallbackContext):
        """Обработчик команды /gen"""
        # Убираем упоминание rate limiting из докстринги
        
        # if not self.rate_limiter.allow():
        #     await update.message.reply_text("⚠️ Слишком много запросов. Пожалуйста, подождите немного.")
        #     return

        # Проверяем наличие и минимальную длину текста
        if not context.args or len(" ".join(context.args)) < config.min_text_length:
            await update.message.reply_text(f"📝 Минимум {config.min_text_length} символа")
            return

        # Проверяем доступность очереди
        # Подсчитываем занятые слоты: задания в очереди + текущее обрабатываемое
        total_slots_used = self.tasks_queue.qsize() + (1 if self.is_processing else 0)
        
        if total_slots_used >= config.max_queue_size:
            await update.message.reply_text(
                f"🔴 Очередь заполнена (максимум {config.max_queue_size} заданий). "
                f"Пожалуйста, попробуйте позже или используйте команду /status для проверки состояния очереди."
            )
            return

        # Подготовка и обрезка текста ДО отправки в генерацию
        user_text = " ".join(context.args)
        
        # Обрезаем текст, если он превышает лимит
        original_length = len(user_text)
        if original_length > config.max_text_length:
            user_text = user_text[:config.max_text_length]
            # Информируем пользователя об обрезке текста
            await update.message.reply_text(
                f"⚠️ Ваш текст был обрезан с {original_length} до {config.max_text_length} символов."
            )
        
        # Отправляем сообщение о добавлении в очередь
        # Показываем корректную позицию, учитывая текущий генерируемый файл и все задания в очереди
        queue_size = self.tasks_queue.qsize()
        
        # Вычисляем реальную позицию: если есть обрабатываемое задание, то +1 к позиции
        real_position = queue_size + 1 + (1 if self.is_processing else 0)

        status_message = await update.message.reply_text(
            f"⏳ Задание добавлено в очередь. Позиция в очереди: {real_position}."
        )
        
        # Создаем и добавляем задание в очередь
        task = AudioTask(text=user_text, update=update, status_message=status_message)
        self.tasks_queue.put(task)
        
        # Запускаем обработчик очереди, если он еще не запущен
        if not self.queue_processor_running:
            asyncio.create_task(self.process_queue())

    async def process_queue(self):
        """Асинхронный обработчик очереди заданий с защитой от зависания при ошибках"""
        self.queue_processor_running = True
        self.current_task = None  # Добавляем отслеживание текущей задачи
        
        while not self.tasks_queue.empty():
            task = None
            try:
                # Получаем задание из очереди
                task = self.tasks_queue.get()
                self.current_task = task  # Сохраняем текущую задачу для отображения в статусе
                
                # Замеряем время начала обработки
                # start_time = datetime.now()
                # print(f"Начало обработки задания в {start_time.strftime('%H:%M:%S.%f')}")
                
                # Обновляем статус для текущего задания
                if task.status_message:
                    await task.status_message.edit_text("⏳ Начинаю генерацию аудиофайла...")
                
                # Устанавливаем флаг занятости
                self.is_processing = True
                
                # Получаем текущий event loop
                loop = asyncio.get_running_loop()
                
                # Запускаем генерацию в отдельном потоке
                future = self.executor.submit(self.generate_audio, task.text)
                
                # Ожидаем завершения генерации с меньшей частотой проверок
                # На CPU операция может быть долгой, увеличиваем интервал проверки
                while not future.done():
                    await asyncio.sleep(1.0)  # Увеличиваем до 1 секунды на CPU
                
                # Получаем результат генерации
                audio_path = future.result()
                
                # Замеряем время до отправки
                # gen_complete_time = datetime.now()
                # print(f"Время до отправки: {(gen_complete_time - start_time).total_seconds():.2f} сек")
                
                # Обрабатываем результат
                await self.handle_audio_generated(task.update, audio_path, task.status_message)
                
                # Замеряем общее время
                # end_time = datetime.now()
                # print(f"Общее время обработки задания: {(end_time - start_time).total_seconds():.2f} сек")
                
            except Exception as e:
                print(f"Ошибка при обработке задания из очереди: {e}")
                
                # Уведомляем пользователя, используя task, если оно определено
                try:
                    if task and task.status_message:
                        await task.status_message.edit_text("🚫 Произошла ошибка при обработке задания.")
                    elif task:
                        await task.update.message.reply_text("🚫 Произошла ошибка при обработке задания.")
                except Exception as notify_error:
                    print(f"Не удалось уведомить пользователя об ошибке: {notify_error}")
            
            finally:
                # Сбрасываем флаг занятости и текущую задачу
                self.is_processing = False
                self.current_task = None
                
                # Если task было получено, отмечаем задание как выполненное
                if task is not None:
                    self.tasks_queue.task_done()
                
                # Обновляем статус оставшихся заданий
                # Для этого нужно будет преобразовать очередь в список временно
                remaining_tasks = list(self.tasks_queue.queue)
                
                # Важно! Показываем правильное общее количество заданий
                # Это количество оставшихся в очереди + 1 (если идет обработка)
                total_tasks = len(remaining_tasks) + (1 if self.is_processing else 0)
                
                for idx, queued_task in enumerate(remaining_tasks):
                    if queued_task.status_message:
                        try:
                            # Позиция в очереди: индекс + 1 (для 1-indexed счета) + 1 (если идет обработка)
                            position = idx + 1 + (1 if self.is_processing else 0)
                            
                            await queued_task.status_message.edit_text(
                                f"⏳ Ожидание в очереди. Позиция: {position} из {total_tasks}."
                            )
                        except Exception as e:
                            print(f"Ошибка при обновлении статусного сообщения: {e}")
        
        self.queue_processor_running = False

    async def handle_audio_generated(self, update: Update, audio_path: str, status_message=None):
        """Обработчик сгенерированного аудио с обновлением статуса"""
        try:
            if audio_path:
                # Обновляем статусное сообщение, если оно есть
                if status_message:
                    await status_message.edit_text("✅ Аудио сгенерировано, отправляю...")
                
                # Отправляем аудио (файл будет удален внутри send_audio)
                await self.send_audio(update, audio_path)
                
                # Обновляем итоговый статус
                if status_message:
                    await status_message.edit_text("✅ Аудио успешно отправлено!")
            else:
                # В случае ошибки
                if status_message:
                    await status_message.edit_text("🚫 Ошибка генерации файла.")
                else:
                    await update.message.reply_text("🚫 Ошибка генерации файла.")
        except Exception as e:
            print(f"Ошибка при обработке сгенерированного аудио: {e}")
            # Уведомляем пользователя об ошибке
            if status_message:
                await status_message.edit_text("🚫 Произошла ошибка при отправке аудио.")
            else:
                await update.message.reply_text("🚫 Произошла ошибка при отправке аудио.")
            
            # Дополнительная проверка, что файл удален, если произошла ошибка отправки
            if audio_path and os.path.exists(audio_path):
                try:
                    os.remove(audio_path)
                    print(f"Файл {audio_path} удален после ошибки отправки")
                except Exception as del_error:
                    print(f"Не удалось удалить файл {audio_path} после ошибки: {del_error}")
        finally:
            # Гарантированно освобождаем флаг занятости
            self.is_processing = False

    async def send_audio(self, update: Update, audio_path: str):
        """Асинхронная отправка аудиофайла с повторными попытками"""
        for attempt in range(3):  # Простая попытка повтора до 3 раз
            try:
                if not os.path.exists(audio_path):
                    await update.message.reply_text("🚫 Файл для отправки не найден.")
                    return
                
                with open(audio_path, 'rb') as audio_file:
                    await update.message.reply_audio(audio=audio_file)
                return  # Успешно отправили - выходим
            except Exception as e:
                if attempt == 2:  # Последняя попытка
                    await update.message.reply_text("🚫 Не удалось отправить аудиофайл.")
                else:
                    await asyncio.sleep(2)  # Пауза перед следующей попыткой
            finally:
                if os.path.exists(audio_path):
                    os.remove(audio_path)

    def get_memory_usage(self):
        """Получает информацию о памяти с кэшированием (обновление раз в 10 секунд)"""
        if not HAS_PSUTIL:
            return None
            
        now = datetime.now()
        
        # Если кэш устарел или отсутствует
        if (self.memory_usage_cache["timestamp"] is None or
                (now - self.memory_usage_cache["timestamp"]).total_seconds() > 10):
            try:
                process = psutil.Process(os.getpid())
                memory = process.memory_info().rss / 1024 / 1024  # в МБ
                self.memory_usage_cache = {
                    "value": memory,
                    "timestamp": now
                }
            except Exception as e:
                print(f"Ошибка при получении информации о памяти: {e}")
                return None
                
        return self.memory_usage_cache["value"]

    async def status_command(self, update: Update, context: CallbackContext):
        """Обработчик команды /status с информацией о состоянии очереди"""
        # Получаем размер очереди и вычисляем общее количество занятых слотов
        queue_size = self.tasks_queue.qsize()
        total_slots_used = queue_size + (1 if self.is_processing else 0)
        remaining_slots = config.max_queue_size - total_slots_used
        
        # Базовая информация о состоянии системы
        status_lines = [
            "📊 Статус системы:\n",
            f"{'🟢 Свободен' if not self.is_processing else '🟡 В процессе генерации'}"
        ]
        
        # Информация о занятых слотах очереди
        status_lines.append(f"📋 Слоты очереди: {total_slots_used} из {config.max_queue_size} (свободно: {remaining_slots})")
        
        # Получаем список заданий из очереди для отображения
        queue_items = list(self.tasks_queue.queue)
        
        # Если есть текущее задание в обработке, показываем его отдельно
        if self.is_processing and self.current_task:
            status_lines.append(f"🔄 Сейчас генерируется: запрос от {self.current_task.update.effective_user.first_name} "
                               f"(добавлен {self.current_task.created_at.strftime('%H:%M:%S')})")
        
        # Отображаем все задания в очереди
        if queue_items:
            status_lines.append(f"📋 Задания в очереди ({len(queue_items)}):")
            for i, task in enumerate(queue_items, start=1):
                status_lines.append(
                    f"   {i}. ⏳ В очереди: запрос от {task.update.effective_user.first_name} "
                    f"(добавлен {task.created_at.strftime('%H:%M:%S')})"
                )
        else:
            status_lines.append("📋 Нет ожидающих заданий в очереди")
        
        # Добавляем информацию о памяти
        memory_usage = self.get_memory_usage()
        if memory_usage is not None:
            status_lines.append(f"💾 Использование памяти: {memory_usage:.1f} МБ")
        
        # Формируем итоговое сообщение
        status_message = "\n".join(status_lines)
        await update.message.reply_text(status_message)

    async def start_command(self, update: Update, context: CallbackContext):
        """Обработчик команды /start с информацией о боте и очереди"""
        queue_info = self._get_queue_status_text()
        
        welcome_text = (
            f"👋 Привет, {update.effective_user.first_name}!\n\n"
            "🎙 Я бот для генерации аудио с голосом Путина.\n\n"
            "Как использовать:\n"
            "- Отправь команду /gen с текстом для синтеза\n"
            "- Используй /status для проверки состояния системы\n\n"
            "Ограничения:\n"
            f"- Минимальная длина текста: {config.min_text_length} символа\n"
            f"- Максимальная длина текста: {config.max_text_length} символов\n"
            f"- Максимальное количество заданий в очереди: {config.max_queue_size}\n\n"
            "Текущий статус очереди:\n"
            f"{queue_info}"
        )
        
        await update.message.reply_text(welcome_text)

    async def error_handler(self, update: Update, context: CallbackContext):
        """Улучшенный обработчик ошибок с обязательным снятием флага занятости"""
        print(f"Ошибка при обработке обновления: {context.error}")
        
        error_message = "🚨 Произошла ошибка."
        if update and update.message:
            await update.message.reply_text(f"{error_message} Попробуйте снова позже.")
        
        # Обязательно сбрасываем флаг занятости при любой ошибке
        self.is_processing = False
        
        # Также нужно разблокировать обработку очереди, если произошла ошибка
        # в процессе обработки очереди
        if not self.tasks_queue.empty() and not self.queue_processor_running:
            # Перезапускаем обработчик очереди
            asyncio.create_task(self.process_queue())

    def cleanup_old_files(self):
        """Оптимизированная очистка старых файлов"""
        try:
            if os.path.exists("temp_audio"):
                files = os.listdir("temp_audio")
                if not files:
                    return  # Директория пуста, быстрый выход
                    
                for filename in files:
                    file_path = os.path.join("temp_audio", filename)
                    if os.path.isfile(file_path):
                        try:
                            os.remove(file_path)
                            print(f"Удален старый временный файл: {file_path}")
                        except Exception as e:
                            print(f"Не удалось удалить файл {file_path}: {e}")
        except Exception as e:
            print(f"Ошибка при очистке временных файлов: {e}")

    def _get_queue_status_text(self) -> str:
        """Формирует текст с информацией о состоянии очереди"""
        # Получаем размер очереди и вычисляем общее количество занятых слотов
        queue_size = self.tasks_queue.qsize()
        total_slots_used = queue_size + (1 if self.is_processing else 0)
        remaining_slots = config.max_queue_size - total_slots_used
        
        if total_slots_used == 0:
            return f"📋 Очередь пуста (доступно {config.max_queue_size} слотов)"
        
        # Формируем основную информацию о состоянии очереди
        queue_info = f"📋 Слоты очереди: {total_slots_used} из {config.max_queue_size} (свободно: {remaining_slots})"
        
        # Информация о текущем задании в обработке
        current_task_info = ""
        if self.is_processing and self.current_task:
            current_task_info = (
                f"🔄 Сейчас генерируется: запрос от {self.current_task.update.effective_user.first_name} "
                f"(добавлен {self.current_task.created_at.strftime('%H:%M:%S')})\n"
            )
        
        # Получаем список заданий из очереди для отображения
        queue_items = list(self.tasks_queue.queue)
        
        # Формируем список всех заданий в очереди
        tasks_info = []
        for i, task in enumerate(queue_items, start=1):
            tasks_info.append(
                f"   {i}. ⏳ В очереди: запрос от {task.update.effective_user.first_name} "
                f"(добавлен {task.created_at.strftime('%H:%M:%S')})"
            )
        
        tasks_header = f"📋 Задания в очереди ({len(tasks_info)}):\n" if tasks_info else ""
        tasks_info_str = "\n".join(tasks_info)
        
        # Собираем полную информацию о состоянии очереди
        return f"{queue_info}\n{current_task_info}{tasks_header}{tasks_info_str}"

def main():
    # Создаем и конфигурируем менеджер бота
    bot_manager = BotManager()
    
    # Загружаем TTS модель при запуске для моментальной готовности
    bot_manager.initialize_tts()

    # Инициализируем приложение Telegram
    application = Application.builder().token(config.token).build()

    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", bot_manager.start_command))
    application.add_handler(CommandHandler("gen", bot_manager.gen_command))
    application.add_handler(CommandHandler("status", bot_manager.status_command))
    
    # Регистрация обработчика ошибок
    application.add_error_handler(bot_manager.error_handler)
    
    # Запуск асинхронного бота
    print("Бот запущен и готов к работе...")
    
    # Запускаем очистку файлов сразу при первой генерации
    bot_manager.cleanup_old_files()
    
    # Запускаем приложение 
    application.run_polling()

if __name__ == "__main__":
    main()
