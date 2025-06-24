import logging
import aiohttp
from datetime import datetime, timedelta, time,timezone
import sys
import asyncio
import json
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
# --- Клас ElasticsearchHandler ---
class ElasticsearchHandler(logging.Handler):
    def __init__(self, hosts, index_name, service_name="default-service", http_auth=None): # <--- ДОДАНО http_auth
        super().__init__()
        if isinstance(hosts, str):
            self.hosts = [hosts]
        else:
            self.hosts = hosts
        self.index_name = index_name
        self.service_name = service_name
        self.es_url = (
            f"{self.hosts[0]}/{self.index_name}/_doc"
        )
        self.auth = None # <--- Зберігаємо об'єкт BasicAuth
        if http_auth and len(http_auth) == 2:
            self.auth = aiohttp.BasicAuth(login=http_auth[0], password=http_auth[1])

    def format_record_for_es(self, record: logging.LogRecord):
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc)
        timestamp_str = ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        log_entry = {
            "project_name": self.service_name,
            "version": "1",
            "timestamp": timestamp_str,
            "level": record.levelname,
            "message": record.getMessage(),
            "logger_name": record.name,
            "pathname": record.pathname,
            "filename": record.filename,
            "module": record.module,
            "lineno": record.lineno,
            "funcName": record.funcName,
        }

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            log_entry["stack_trace"] = self.formatStack(record.stack_info)

        if isinstance(record.msg, Exception) and not isinstance(
            log_entry["message"], str
        ):
            log_entry["message"] = str(record.msg)

        return log_entry

    async def _send_to_es(self, log_document):
        try:
            # Передаємо self.auth до ClientSession
            async with aiohttp.ClientSession(auth=self.auth) as session: # <--- ДОДАНО auth=self.auth
                async with session.post(
                    self.es_url,
                    data=json.dumps(log_document),
                    headers={"Content-Type": "application/json"},
                ) as response:
                    if response.status >= 300:
                        response_text = await response.text()
                        print(
                            f"Помилка відправки логу в Elasticsearch: {response.status} {response.reason}. Відповідь: {response_text}",
                            file=sys.stderr
                        )
        except aiohttp.ClientError as e:
            print(
                f"Не вдалося відправити лог в Elasticsearch (помилка клієнта aiohttp): {e}",
                file=sys.stderr
            )
        except Exception as e:
            print(f"Неочікувана помилка при відправці логу в Elasticsearch: {e}", file=sys.stderr)

    def emit(self, record: logging.LogRecord):
        try:
            log_document = self.format_record_for_es(record)
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._send_to_es(log_document))
            else:
                print(
                    f"Asyncio цикл не запущено. Лог для ES не відправлено: {log_document}",
                    file=sys.stderr
                )
        except Exception as e:
            print(f"Помилка в ElasticsearchHandler.emit: {e}", file=sys.stderr)
            self.handleError(record)
# --- Кінець класу ElasticsearchHandler ---
# --- Обробник для Elasticsearch ---
ELASTICSEARCH_HOST = "http://38.180.96.111:9200" # Публічний IP вашого Docker-сервера
ELASTICSEARCH_USERNAME = "elastic"
ELASTICSEARCH_PASSWORD = "981We$kidRt#4_124fgF" # Ваш пароль
ELASTICSEARCH_INDEX = "agentmonitor"
SERVICE_NAME = "AgentMonitor"

es_handler = ElasticsearchHandler(
    hosts=[ELASTICSEARCH_HOST],
    index_name=ELASTICSEARCH_INDEX,
    service_name=SERVICE_NAME,
    http_auth=(ELASTICSEARCH_USERNAME, ELASTICSEARCH_PASSWORD)
)
es_handler.setLevel(logging.INFO)
logger.addHandler(es_handler)