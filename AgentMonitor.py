from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import (
    PeerIdInvalidError,
    ChatWriteForbiddenError,
    UserBannedInChannelError,
    SessionPasswordNeededError,
)
import asyncio
import aiohttp
import json
from datetime import datetime, timedelta, time
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
import sys
import pytz

#------------------------------------------------------------------------------
# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("monitor.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

@dataclass
class MonitoringConfig:
    enabled: bool
    day_inactive_minutes: int
    night_inactive_minutes: int


@dataclass
class NightHoursConfig:
    start: str  # "22:00"
    end: str  # "08:00"


@dataclass
class ApiRebootConfig:
    enabled: bool
    url: Optional[str] = None
    method: str = "GET"
    headers: Optional[Dict] = None
    payload: Optional[Dict] = None


@dataclass
class GroupConfig:
    chat_id: int
    name: str
    description: str
    monitoring: MonitoringConfig
    api_reboot: ApiRebootConfig


class TelegramMultiMonitor:
    def __init__(self, config_file: str = "config.json"):
        self.config = self.load_config(config_file)
        self.client = None
        self.notification_chat_id = None
        self.timezone = None

        # Словники для зберігання стану по кожній групі
        self.last_message_time: Dict[int, datetime] = {}
        self.notification_sent: Dict[int, bool] = {}
        self.chat_accessible: Dict[int, bool] = {}
        self.api_reboot_sent: Dict[int, bool] = {}

        # Ініціалізуємо часову зону
        self.setup_timezone()

    def setup_timezone(self):
        """Налаштовує часову зону"""
        try:
            timezone_name = self.config["global_settings"].get(
                "timezone", "Europe/Kiev"
            )
            self.timezone = pytz.timezone(timezone_name)
            logger.info(f"Використовується часова зона: {timezone_name}")
        except Exception as e:
            logger.warning(
                f"Помилка налаштування часової зони: {e}. Використовується UTC"
            )
            self.timezone = pytz.UTC

    def get_night_hours(self) -> NightHoursConfig:
        """Повертає налаштування нічних годин"""
        night_config = self.config["global_settings"]["night_hours"]
        return NightHoursConfig(start=night_config["start"], end=night_config["end"])

    def is_night_time(self, dt: datetime = None) -> bool:
        """Перевіряє чи зараз нічний час"""
        if dt is None:
            dt = datetime.now(self.timezone)

        night_hours = self.get_night_hours()

        try:
            # Парсимо час початку і кінця ночі
            start_time = datetime.strptime(night_hours.start, "%H:%M").time()
            end_time = datetime.strptime(night_hours.end, "%H:%M").time()
            current_time = dt.time()

            # Якщо нічний період не переходить через північ (наприклад, 23:00-06:00)
            if start_time > end_time:
                return current_time >= start_time or current_time <= end_time
            # Якщо нічний період в межах одного дня (наприклад, 01:00-05:00)
            else:
                return start_time <= current_time <= end_time

        except Exception as e:
            logger.error(f"Помилка визначення нічного часу: {e}")
            return False

    def get_current_timeout_for_group(self, group: GroupConfig) -> int:
        """Повертає поточний таймаут для групи в залежності від часу доби"""
        is_night = self.is_night_time()

        if is_night:
            return group.monitoring.night_inactive_minutes
        else:
            return group.monitoring.day_inactive_minutes

    def get_time_period_name(self) -> str:
        """Повертає назву поточного періоду часу"""
        return "🌙 Ніч" if self.is_night_time() else "☀️ День"

    def load_config(self, config_file: str) -> dict:
        """Завантажує конфігурацію з файлу"""
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
            logger.info(f"Конфігурацію завантажено з {config_file}")

            # Перевіряємо наявність session_string
            if not config["telegram"].get("session_string"):
                logger.error(
                    "session_string порожній! Запустіть generate_session.py для створення сесії"
                )
                raise ValueError("session_string порожній")

            return config
        except FileNotFoundError:
            logger.error(f"Файл конфігурації {config_file} не знайдено")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Помилка парсингу JSON: {e}")
            raise

    def get_groups(self) -> List[GroupConfig]:
        """Повертає список груп з конфігурації"""
        groups = []
        for group_data in self.config["groups"]:
            # Моніторинг конфігурація
            monitoring_config = MonitoringConfig(
                enabled=group_data["monitoring"]["enabled"],
                day_inactive_minutes=group_data["monitoring"]["day_inactive_minutes"],
                night_inactive_minutes=group_data["monitoring"][
                    "night_inactive_minutes"
                ],
            )

            # API конфігурація
            api_config = ApiRebootConfig(
                enabled=group_data["api_reboot"]["enabled"],
                url=group_data["api_reboot"].get("url"),
                method=group_data["api_reboot"].get("method", "GET"),
                headers=group_data["api_reboot"].get("headers"),
                payload=group_data["api_reboot"].get("payload"),
            )

            group = GroupConfig(
                chat_id=group_data["chat_id"],
                name=group_data["name"],
                description=group_data["description"],
                monitoring=monitoring_config,
                api_reboot=api_config,
            )
            groups.append(group)
        return groups

    def get_enabled_groups(self) -> List[GroupConfig]:
        """Повертає тільки групи з увімкненим моніторингом"""
        return [group for group in self.get_groups() if group.monitoring.enabled]

    async def initialize_client(self):
        """Ініціалізує Telegram клієнта"""
        telegram_config = self.config["telegram"]

        try:
            session_string = telegram_config["session_string"]
            if not session_string or session_string.strip() == "":
                raise ValueError("Порожній session_string")

            session = StringSession(session_string)

            self.client = TelegramClient(
                session, telegram_config["api_id"], telegram_config["api_hash"]
            )

            await self.client.start()

            # Перевіряємо чи клієнт авторизований
            if not await self.client.is_user_authorized():
                logger.error("Клієнт не авторизований. Перегенеруйте session_string")
                raise Exception("Клієнт не авторизований")

            # Отримуємо інформацію про користувача
            me = await self.client.get_me()
            logger.info(
                f"Telegram клієнт запущено. Авторизовано як: {me.first_name} (@{me.username})"
            )

        except ValueError as e:
            logger.error(f"Помилка session_string: {e}")
            logger.error("Запустіть generate_session.py для створення нової сесії")
            raise
        except Exception as e:
            logger.error(f"Помилка ініціалізації клієнта: {e}")
            if "Incorrect padding" in str(e):
                logger.error(
                    "Проблема з форматом session_string. Перегенеруйте сесію за допомогою generate_session.py"
                )
            raise

    async def validate_chat_access(self, group: GroupConfig) -> bool:
        """Перевіряє доступ до чату"""
        try:
            chat = await self.client.get_entity(group.chat_id)
            chat_title = getattr(chat, "title", f"Chat {group.chat_id}")
            logger.info(f"Доступ до чату '{group.name}' ({chat_title}) підтверджено")
            self.chat_accessible[group.chat_id] = True
            return True
        except PeerIdInvalidError:
            logger.error(f"Невірний ID чату для групи '{group.name}': {group.chat_id}")
            self.chat_accessible[group.chat_id] = False
            return False
        except Exception as e:
            logger.error(f"Помилка при перевірці доступу до групи '{group.name}': {e}")
            self.chat_accessible[group.chat_id] = False
            return False

    async def setup_notification_channel(self):
        """Налаштовує канал для сповіщень"""
        notification_user = self.config["global_settings"]["notification_user_id"]

        if notification_user == "me":
            try:
                me = await self.client.get_me()
                self.notification_chat_id = me.id
                logger.info(
                    "Повідомлення будуть відправлятися у 'Збережені повідомлення'"
                )
                return True
            except Exception as e:
                logger.error(f"Помилка при отриманні власного ID: {e}")
                return False
        else:
            self.notification_chat_id = notification_user
            return True

    async def send_notification(self, message: str) -> bool:
        """Безпечно відправляє повідомлення"""
        if not self.notification_chat_id:
            logger.error("Не встановлено канал для повідомлень")
            return False

        try:
            await self.client.send_message(self.notification_chat_id, message)
            return True
        except Exception as e:
            logger.error(f"Помилка при відправці повідомлення: {e}")
            return False

    async def call_api_reboot(self, group: GroupConfig) -> bool:
        """Викликає API для перезапуску"""
        if not group.api_reboot.enabled or not group.api_reboot.url:
            return False

        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                kwargs = {
                    "url": group.api_reboot.url,
                    "headers": group.api_reboot.headers or {},
                }

                if (
                    group.api_reboot.method.upper() == "POST"
                    and group.api_reboot.payload
                ):
                    kwargs["json"] = group.api_reboot.payload

                method = getattr(session, group.api_reboot.method.lower())

                logger.info(
                    f"Викликаю API reboot для групи '{group.name}': {group.api_reboot.method} {group.api_reboot.url}"
                )

                async with method(**kwargs) as response:
                    response_text = await response.text()

                    if response.status in [200, 201, 202]:
                        logger.info(
                            f"API reboot успішно викликано для групи '{group.name}'. Статус: {response.status}"
                        )
                        logger.info(f"Відповідь сервера: {response_text}")
                        return True
                    else:
                        logger.error(
                            f"API reboot невдалий для групи '{group.name}'. Статус: {response.status}"
                        )
                        logger.error(f"Відповідь сервера: {response_text}")
                        return False

        except asyncio.TimeoutError:
            logger.error(f"Таймаут при виклику API reboot для групи '{group.name}'")
            return False
        except Exception as e:
            logger.error(
                f"Помилка при виклику API reboot для групи '{group.name}': {e}"
            )
            return False

    async def check_inactivity(self):
        """Перевіряє неактивність у всіх чатах з урахуванням день/ніч режимів"""
        enabled_groups = self.get_enabled_groups()

        logger.info(
            f"Запущено перевірку неактивності для {len(enabled_groups)} груп з день/ніч режимами"
        )
        night_hours = self.get_night_hours()
        logger.info(f"Нічні години: {night_hours.start} - {night_hours.end}")

        while True:
            try:
                current_time = datetime.now(self.timezone)
                is_night = self.is_night_time(current_time)
                period_name = self.get_time_period_name()

                # Логуємо зміну періоду
                if (
                    not hasattr(self, "_last_period_night")
                    or self._last_period_night != is_night
                ):
                    logger.info(
                        f"Перехід на {period_name} режим о {current_time.strftime('%H:%M:%S')}"
                    )
                    self._last_period_night = is_night

                for group in enabled_groups:
                    chat_id = group.chat_id

                    # Перевіряємо чи є доступ до чату
                    if not self.chat_accessible.get(chat_id, False):
                        continue

                    if chat_id not in self.last_message_time:
                        continue

                    last_time = self.last_message_time[chat_id]
                    time_diff = current_time - last_time

                    # Отримуємо поточний таймаут для цієї групи
                    current_timeout_minutes = self.get_current_timeout_for_group(group)
                    timeout_threshold = timedelta(minutes=current_timeout_minutes)

                    # Якщо пройшло більше встановленого часу для цієї групи
                    if time_diff > timeout_threshold:
                        # Відправляємо сповіщення (якщо ще не відправляли)
                        if not self.notification_sent.get(chat_id, False):
                            await self.send_inactivity_notification(
                                group, time_diff, is_night, current_timeout_minutes
                            )
                            self.notification_sent[chat_id] = True

                        # Викликаємо API reboot (якщо ще не викликали і включено)
                        if group.api_reboot.enabled and not self.api_reboot_sent.get(
                            chat_id, False
                        ):
                            if await self.call_api_reboot(group):
                                self.api_reboot_sent[chat_id] = True
                                await self.send_api_reboot_notification(
                                    group, is_night, current_timeout_minutes
                                )

                    # Скидаємо флаги при поновленні активності або зміні періоду
                    else:
                        if self.notification_sent.get(
                            chat_id, False
                        ) or self.api_reboot_sent.get(chat_id, False):
                            logger.info(
                                f"Активність відновлена в групі '{group.name}' ({period_name})"
                            )
                        self.notification_sent[chat_id] = False
                        self.api_reboot_sent[chat_id] = False

            except Exception as e:
                logger.error(f"Помилка при перевірці неактивності: {e}")

            # Чекаємо глобальний інтервал
            check_interval = self.config["global_settings"]["check_interval_seconds"]
            await asyncio.sleep(check_interval)

    async def send_inactivity_notification(
        self,
        group: GroupConfig,
        time_diff: timedelta,
        is_night: bool,
        current_timeout: int,
    ):
        """Відправляє сповіщення про неактивність з інформацією про день/ніч"""
        minutes_inactive = int(time_diff.total_seconds() // 60)
        period_icon = "🌙" if is_night else "☀️"
        period_name = "Нічний" if is_night else "Денний"

        message = (
            f"⚠️ **УВАГА: Неактивність у групі!**\n\n"
            f"📱 Група: {group.name}\n"
            f"📝 Опис: {group.description}\n"
            f"🆔 ID: `{group.chat_id}`\n"
            f"⏰ Останнє повідомлення: {self.last_message_time[group.chat_id].strftime('%H:%M:%S')}\n"
            f"🕐 Час неактивності: {minutes_inactive} хвилин\n"
            f"{period_icon} Режим: {period_name}\n"
            f"⏳ Поріг ({period_name.lower()}): {current_timeout} хвилин\n"
            f"📊 Налаштування: День {group.monitoring.day_inactive_minutes}хв / Ніч {group.monitoring.night_inactive_minutes}хв\n"
            f"📅 Дата: {datetime.now(self.timezone).strftime('%d.%m.%Y %H:%M:%S')}\n"
            f"🔄 API Reboot: {'Увімкнено' if group.api_reboot.enabled else 'Вимкнено'}"
        )

        await self.send_notification(message)
        logger.info(
            f"Відправлено сповіщення про неактивність для групи '{group.name}' ({period_name} режим: {current_timeout} хв)"
        )

    async def send_api_reboot_notification(
        self, group: GroupConfig, is_night: bool, current_timeout: int
    ):
        """Відправляє сповіщення про виклик API reboot"""
        period_icon = "🌙" if is_night else "☀️"
        period_name = "Нічний" if is_night else "Денний"

        message = (
            f"🔄 **API REBOOT ВИКЛИКАНО**\n\n"
            f"📱 Група: {group.name}\n"
            f"🆔 ID: `{group.chat_id}`\n"
            f"{period_icon} Режим: {period_name}\n"
            f"⏳ Поріг неактивності: {current_timeout} хвилин\n"
            f"🌐 URL: {group.api_reboot.url}\n"
            f"📡 Метод: {group.api_reboot.method}\n"
            f"🔑 Headers: {list(group.api_reboot.headers.keys()) if group.api_reboot.headers else 'Немає'}\n"
            f"⏰ Час: {datetime.now(self.timezone).strftime('%H:%M:%S %d.%m.%Y')}"
        )

        await self.send_notification(message)
        logger.info(
            f"Відправлено сповіщення про API reboot для групи '{group.name}' ({period_name} режим)"
        )

    def setup_event_handlers(self):
        """Налаштовує обробники подій"""
        enabled_groups = self.get_enabled_groups()
        monitored_chat_ids = [group.chat_id for group in enabled_groups]

        logger.info(f"Налаштовую обробники для {len(monitored_chat_ids)} активних груп")

        @self.client.on(events.NewMessage(chats=monitored_chat_ids))
        async def handle_monitored_message(event):
            """Обробляє повідомлення у відстежуваних чатах"""
            try:
                chat_id = event.chat_id
                current_time = datetime.now(self.timezone)

                # Оновлюємо час останнього повідомлення
                self.last_message_time[chat_id] = current_time

                # Скидаємо флаги
                self.notification_sent[chat_id] = False
                self.api_reboot_sent[chat_id] = False

                # Знаходимо групу та її налаштування
                group = next((g for g in enabled_groups if g.chat_id == chat_id), None)
                group_name = group.name if group else f"Group {chat_id}"

                sender = await event.get_sender()
                sender_name = getattr(sender, "first_name", "Невідомий")

                period_name = self.get_time_period_name()
                logger.info(
                    f"Повідомлення від {sender_name} у групі '{group_name}' о {current_time.strftime('%H:%M:%S')} ({period_name})"
                )

            except Exception as e:
                logger.error(f"Помилка при обробці повідомлення: {e}")

        @self.client.on(events.NewMessage(outgoing=True))
        async def handler_outgoing(event):
            """Обробляє вихідні повідомлення (команди)"""
            try:
                text = event.text.lower().strip() if event.text else ""

                if event.text == "HI":
                    await event.edit("ПРИВІТИК!!!!")
                elif text == "/status":
                    await self.handle_status_command(event)
                elif text == "/test":
                    await self.handle_test_command(event)
                elif text == "/reload":
                    await self.handle_reload_command(event)
                elif text.startswith("/reboot"):
                    await self.handle_manual_reboot_command(event)
                elif text == "/groups":
                    await self.handle_groups_command(event)
                elif text == "/time":
                    await self.handle_time_command(event)

            except Exception as e:
                logger.error(f"Помилка при обробці вихідного повідомлення: {e}")

    async def handle_time_command(self, event):
        """Показує поточний час та налаштування день/ніч"""
        current_time = datetime.now(self.timezone)
        is_night = self.is_night_time(current_time)
        night_hours = self.get_night_hours()

        period_icon = "🌙" if is_night else "☀️"
        period_name = "Нічний" if is_night else "Денний"

        message = (
            f"🕐 **Поточний час та налаштування:**\n\n"
            f"📅 Дата і час: {current_time.strftime('%d.%m.%Y %H:%M:%S')}\n"
            f"🌍 Часова зона: {self.timezone}\n"
            f"{period_icon} Поточний режим: {period_name}\n\n"
            f"🌙 Нічні години: {night_hours.start} - {night_hours.end}\n"
            f"☀️ Денні години: решта часу\n\n"
            f"**Поточні таймаути для груп:**\n"
        )

        enabled_groups = self.get_enabled_groups()
        for group in enabled_groups:
            current_timeout = self.get_current_timeout_for_group(group)
            day_timeout = group.monitoring.day_inactive_minutes
            night_timeout = group.monitoring.night_inactive_minutes

            message += (
                f"📱 {group.name}: {current_timeout} хв "
                f"(День: {day_timeout}хв / Ніч: {night_timeout}хв)\n"
            )

        await event.edit(message)

    async def handle_status_command(self, event):
        """Обробляє команду /status з інформацією про день/ніч"""
        all_groups = self.get_groups()
        enabled_groups = self.get_enabled_groups()
        current_time = datetime.now(self.timezone)
        is_night = self.is_night_time(current_time)
        period_icon = "🌙" if is_night else "☀️"
        period_name = "Нічний" if is_night else "Денний"

        status_lines = [
            f"📊 **Статус моніторингу:** {len(enabled_groups)}/{len(all_groups)} груп активні\n"
            f"{period_icon} **Поточний режим:** {period_name}\n"
        ]

        for group in all_groups:
            chat_id = group.chat_id
            status_icon = "✅" if group.monitoring.enabled else "⏸️"

            if chat_id in self.last_message_time and group.monitoring.enabled:
                last_time = self.last_message_time[chat_id]
                time_diff = current_time - last_time
                minutes_inactive = int(time_diff.total_seconds() // 60)

                # Отримуємо поточний таймаут
                current_timeout = self.get_current_timeout_for_group(group)

                # Визначаємо стан на основі поточного порогу
                is_overdue = minutes_inactive >= current_timeout
                overdue_icon = "🔴" if is_overdue else "🟢"

                reboot_status = (
                    "🔄 Викликано"
                    if self.api_reboot_sent.get(chat_id, False)
                    else "⏸️ Очікує"
                )

                status_lines.append(
                    f"{status_icon} **{group.name}** {overdue_icon}\n"
                    f"   🆔 ID: `{chat_id}`\n"
                    f"   ⏰ Останнє: {last_time.strftime('%H:%M:%S')}\n"
                    f"   🕐 Неактивність: {minutes_inactive}/{current_timeout} хв ({period_name.lower()})\n"
                    f"   📊 День/Ніч: {group.monitoring.day_inactive_minutes}/{group.monitoring.night_inactive_minutes} хв\n"
                    f"   ✅ Доступ: {'Так' if self.chat_accessible.get(chat_id, False) else 'Ні'}\n"
                    f"   🔄 API: {'Увімкнено' if group.api_reboot.enabled else 'Вимкнено'}\n"
                    f"   📡 Статус: {reboot_status if group.api_reboot.enabled else 'N/A'}\n"
                )
            else:
                current_timeout = (
                    self.get_current_timeout_for_group(group)
                    if group.monitoring.enabled
                    else 0
                )
                status_lines.append(
                    f"{status_icon} **{group.name}**\n"
                    f"   🆔 ID: `{chat_id}`\n"
                    f"   📊 День/Ніч: {group.monitoring.day_inactive_minutes}/{group.monitoring.night_inactive_minutes} хв\n"
                    f"   ⏳ Поточний поріг: {current_timeout} хв\n"
                    f"   📊 Статус: {'Вимкнено' if not group.monitoring.enabled else 'Немає даних'}\n"
                )

        check_interval = self.config["global_settings"]["check_interval_seconds"]
        night_hours = self.get_night_hours()
        status_lines.append(
            f"\n🔄 Інтервал перевірки: {check_interval} секунд\n"
            f"🌙 Нічні години: {night_hours.start} - {night_hours.end}\n"
            f"🟢 - в межах норми, 🔴 - перевищено поріг"
        )

        await event.edit("\n".join(status_lines))

    async def handle_groups_command(self, event):
        """Показує список всіх груп з день/ніч налаштуваннями"""
        all_groups = self.get_groups()
        is_night = self.is_night_time()
        period_icon = "🌙" if is_night else "☀️"

        groups_lines = [f"👥 **Всі групи в конфігурації:** {period_icon}\n"]

        for i, group in enumerate(all_groups, 1):
            status = "✅ Активна" if group.monitoring.enabled else "⏸️ Вимкнена"
            api_status = "🔄 Так" if group.api_reboot.enabled else "❌ Ні"
            current_timeout = (
                self.get_current_timeout_for_group(group)
                if group.monitoring.enabled
                else 0
            )

            groups_lines.append(
                f"**{i}. {group.name}**\n"
                f"   📝 {group.description}\n"
                f"   🆔 ID: `{group.chat_id}`\n"
                f"   📊 Моніторинг: {status}\n"
                f"   ☀️ День: {group.monitoring.day_inactive_minutes} хв\n"
                f"   🌙 Ніч: {group.monitoring.night_inactive_minutes} хв\n"
                f"   ⏳ Зараз: {current_timeout} хв\n"
                f"   🔄 API Reboot: {api_status}\n"
            )

        await event.edit("\n".join(groups_lines))

    async def handle_test_command(self, event):
        """Обробляє команду /test з інформацією про поточні таймаути"""
        await event.edit("🔄 Перевіряю доступ до всіх груп...")

        all_groups = self.get_groups()
        is_night = self.is_night_time()
        period_icon = "🌙" if is_night else "☀️"
        results = []

        for group in all_groups:
            access = await self.validate_chat_access(group)
            access_icon = "✅" if access else "❌"
            status_icon = "🟢" if group.monitoring.enabled else "⏸️"
            api_icon = "🔄" if group.api_reboot.enabled else "❌"
            current_timeout = (
                self.get_current_timeout_for_group(group)
                if group.monitoring.enabled
                else 0
            )

            results.append(
                f"{access_icon}{status_icon} {group.name} "
                f"({current_timeout}хв{period_icon}) {api_icon}"
            )

        result_text = f"🧪 **Результати тестування:** {period_icon}\n\n" + "\n".join(
            results
        )
        result_text += (
            "\n\n**Легенда:**\n"
            "✅❌ - доступ до чату\n"
            "🟢⏸️ - статус моніторингу\n"
            "🔄❌ - API reboot\n"
            f"(Nхв{period_icon}) - поточний таймаут\n"
            "☀️ - день, 🌙 - ніч"
        )
        await event.edit(result_text)

    async def handle_reload_command(self, event):
        """Обробляє команду /reload"""
        try:
            await event.edit("🔄 Перезавантажую конфігурацію...")
            old_groups_count = len(self.get_enabled_groups())

            self.config = self.load_config("config.json")
            self.setup_timezone()  # Оновлюємо часову зону
            new_groups_count = len(self.get_enabled_groups())

            await event.edit(
                f"✅ Конфігурацію перезавантажено!\n"
                f"📊 Активних груп: {old_groups_count} → {new_groups_count}\n"
                f"🌍 Часова зона: {self.timezone}\n"
                f"{self.get_time_period_name()} Поточний режим"
            )
            logger.info("Конфігурацію перезавантажено через команду")
        except Exception as e:
            await event.edit(f"❌ Помилка перезавантаження: {str(e)}")
            logger.error(f"Помилка перезавантаження конфігурації: {e}")

    async def handle_manual_reboot_command(self, event):
        """Обробляє команду /reboot [назва_групи]"""
        try:
            parts = event.text.split()
            if len(parts) < 2:
                enabled_groups = self.get_enabled_groups()
                group_info = []
                for g in enabled_groups:
                    current_timeout = self.get_current_timeout_for_group(g)
                    period_icon = "🌙" if self.is_night_time() else "☀️"
                    group_info.append(f"• {g.name} ({current_timeout}хв{period_icon})")

                await event.edit(
                    f"❌ Використання: `/reboot назва_групи`\n\n"
                    f"**Доступні групи:**\n" + "\n".join(group_info)
                )
                return

            group_name = " ".join(parts[1:])
            all_groups = self.get_groups()

            target_group = None
            for group in all_groups:
                if group.name.lower() == group_name.lower():
                    target_group = group
                    break

            if not target_group:
                available_groups = []
                for g in all_groups:
                    current_timeout = self.get_current_timeout_for_group(g)
                    period_icon = "🌙" if self.is_night_time() else "☀️"
                    available_groups.append(
                        f"• {g.name} ({current_timeout}хв{period_icon})"
                    )

                await event.edit(
                    f"❌ Група '{group_name}' не знайдена.\n\n"
                    f"**Доступні групи:**\n" + "\n".join(available_groups)
                )
                return

            if not target_group.monitoring.enabled:
                await event.edit(
                    f"❌ Моніторинг вимкнено для групи '{target_group.name}'"
                )
                return

            if not target_group.api_reboot.enabled:
                await event.edit(
                    f"❌ API reboot вимкнено для групи '{target_group.name}'"
                )
                return

            current_timeout = self.get_current_timeout_for_group(target_group)
            period_name = "нічний" if self.is_night_time() else "денний"

            await event.edit(
                f"🔄 Викликаю reboot для групи '{target_group.name}'\n"
                f"({period_name} режим, поріг: {current_timeout} хв)..."
            )

            if await self.call_api_reboot(target_group):
                await event.edit(
                    f"✅ Reboot успішно викликано для групи '{target_group.name}'"
                )
                await self.send_api_reboot_notification(
                    target_group, self.is_night_time(), current_timeout
                )
            else:
                await event.edit(
                    f"❌ Помилка при виклику reboot для групи '{target_group.name}'"
                )

        except Exception as e:
            await event.edit(f"❌ Помилка: {str(e)}")
            logger.error(f"Помилка manual reboot: {e}")

    async def start_monitoring(self):
        """Запускає моніторинг"""
        try:
            # Ініціалізуємо клієнта
            await self.initialize_client()

            # Налаштовуємо канал сповіщень
            if not await self.setup_notification_channel():
                logger.error("Не вдалося налаштувати канал сповіщень")
                return

            # Перевіряємо доступ до увімкнених груп
            enabled_groups = self.get_enabled_groups()
            all_groups = self.get_groups()

            if not enabled_groups:
                logger.error("Немає увімкнених груп для моніторингу")
                return

            accessible_groups = []

            for group in enabled_groups:
                if await self.validate_chat_access(group):
                    accessible_groups.append(group)
                    # Ініціалізуємо дані
                    self.last_message_time[group.chat_id] = datetime.now(self.timezone)
                    self.notification_sent[group.chat_id] = False
                    self.api_reboot_sent[group.chat_id] = False

            if not accessible_groups:
                logger.error("Немає доступних груп для моніторингу")
                return

            # Налаштовуємо обробники подій
            self.setup_event_handlers()

            # Відправляємо стартове повідомлення
            await self.send_start_notification(accessible_groups, all_groups)

            # Запускаємо перевірку неактивності
            asyncio.create_task(self.check_inactivity())

            logger.info("Моніторинг запущено успішно!")
            await self.client.run_until_disconnected()

        except Exception as e:
            logger.error(f"Критична помилка: {e}")

    async def send_start_notification(
        self, accessible_groups: List[GroupConfig], all_groups: List[GroupConfig]
    ):
        """Відправляє повідомлення про початок моніторингу з день/ніч інформацією"""
        check_interval = self.config["global_settings"]["check_interval_seconds"]
        current_time = datetime.now(self.timezone)
        is_night = self.is_night_time(current_time)
        night_hours = self.get_night_hours()
        period_icon = "🌙" if is_night else "☀️"
        period_name = "Нічний" if is_night else "Денний"

        group_list = []
        for group in accessible_groups:
            api_status = "🔄" if group.api_reboot.enabled else "❌"
            current_timeout = self.get_current_timeout_for_group(group)

            group_list.append(
                f"📱 {group.name}\n"
                f"   🆔 `{group.chat_id}`\n"
                f"   ☀️ День: {group.monitoring.day_inactive_minutes} хв\n"
                f"   🌙 Ніч: {group.monitoring.night_inactive_minutes} хв\n"
                f"   ⏳ Зараз ({period_name.lower()}): {current_timeout} хв\n"
                f"   🔄 API: {api_status}"
            )

        disabled_count = len(all_groups) - len(accessible_groups)

        start_message = (
            f"🤖 **Мульти-груповий моніторинг запущено!** {period_icon}\n\n"
            f"👥 Активних груп: {len(accessible_groups)}/{len(all_groups)}\n"
            f"⏸️ Вимкнених груп: {disabled_count}\n"
            f"🔄 Інтервал перевірки: {check_interval} сек\n"
            f"🌍 Часова зона: {self.timezone}\n"
            f"🌙 Нічні години: {night_hours.start} - {night_hours.end}\n"
            f"{period_icon} Поточний режим: {period_name}\n"
            f"🕐 Час запуску: {current_time.strftime('%H:%M:%S %d.%m.%Y')}\n\n"
            f"**Активні групи:**\n" + "\n\n".join(group_list) + "\n\n"
            f"**Команди:**\n"
            f"`/status` - детальний статус\n"
            f"`/groups` - список всіх груп\n"
            f"`/time` - поточний час та режим\n"
            f"`/test` - перевірка доступу\n"
            f"`/reload` - перезавантажити конфігурацію\n"
            f"`/reboot назва_групи` - ручний reboot"
        )

        await self.send_notification(start_message)

async def main():
    try:
        monitor = TelegramMultiMonitor("config.json")
        await monitor.start_monitoring()
    except Exception as e:
        logger.error(f"Помилка запуску: {e}")
        print("\n🔧 Інструкції по налаштуванню:")
        print("1. Запустіть generate_session.py для створення session_string")
        print("2. Скопіюйте отриманий session_string в config.json")
        print("3. Перевірте правильність API_ID та API_HASH")
        print("4. Встановіть pytz: pip install pytz")
        sys.exit(1)

#--------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())