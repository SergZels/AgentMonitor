import asyncio
import subprocess
import signal
from datetime import datetime
from typing import Optional, Dict, Any
import logging

# Налаштування логування
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Глобальні змінні для логів
monitor_logs = []
max_log_lines = 100


class AsyncMonitorController:
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.status = "stopped"
        self.start_time: Optional[datetime] = None
        self.log_file = "monitor.log"
        self.log_task: Optional[asyncio.Task] = None

    def get_status(self) -> Dict[str, Any]:
        """Повертає поточний статус моніторингу"""
        if self.process and self.process.poll() is None:
            return {
                "status": "running",
                "pid": self.process.pid,
                "start_time": self.start_time.isoformat() if self.start_time else None,
                "uptime": str(datetime.now() - self.start_time)
                if self.start_time
                else None,
            }
        else:
            return {
                "status": "stopped",
                "pid": None,
                "start_time": None,
                "uptime": None,
            }

    async def start_monitor(self) -> Dict[str, Any]:
        """Запускає моніторинг асинхронно"""
        if self.process and self.process.poll() is None:
            return {"success": False, "message": "Моніторинг вже запущено"}

        try:
            logger.info("🚀 Запуск моніторингу...")

            # Запускаємо основний скрипт
            self.process = subprocess.Popen(
                ["python", "main.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
            )

            self.start_time = datetime.now()
            self.status = "running"

            # Запускаємо асинхронне читання логів
            self.log_task = asyncio.create_task(self._read_logs_async())

            logger.info(f"✅ Моніторинг запущено (PID: {self.process.pid})")

            return {
                "success": True,
                "message": f"Моніторинг запущено (PID: {self.process.pid})",
                "pid": self.process.pid,
            }

        except Exception as e:
            logger.error(f"❌ Помилка запуску: {e}")
            return {"success": False, "message": f"Помилка запуску: {str(e)}"}

    async def stop_monitor(self) -> Dict[str, Any]:
        """Зупиняє моніторинг асинхронно"""
        if not self.process or self.process.poll() is not None:
            return {"success": False, "message": "Моніторинг не запущено"}

        try:
            logger.info("🛑 Зупинка моніторингу...")
            pid = self.process.pid

            # Зупиняємо task читання логів
            if self.log_task and not self.log_task.done():
                self.log_task.cancel()
                try:
                    await self.log_task
                except asyncio.CancelledError:
                    pass

            # Graceful shutdown
            self.process.terminate()

            # Асинхронно чекаємо завершення процесу
            try:
                await asyncio.wait_for(
                    asyncio.create_task(self._wait_for_process()), timeout=10.0
                )
            except asyncio.TimeoutError:
                logger.warning("⚠️ Процес не завершився, примусове завершення...")
                self.process.kill()
                await asyncio.create_task(self._wait_for_process())

            self.process = None
            self.start_time = None
            self.status = "stopped"
            self.log_task = None

            logger.info(f"✅ Моніторинг зупинено (PID: {pid})")

            return {"success": True, "message": f"Моніторинг зупинено (PID: {pid})"}

        except Exception as e:
            logger.error(f"❌ Помилка зупинки: {e}")
            return {"success": False, "message": f"Помилка зупинки: {str(e)}"}

    async def restart_monitor(self) -> Dict[str, Any]:
        """Перезапускає моніторинг асинхронно"""
        logger.info("🔄 Перезапуск моніторингу...")

        stop_result = await self.stop_monitor()
        if stop_result["success"] or "не запущено" in stop_result["message"]:
            # Коротка асинхронна пауза
            await asyncio.sleep(2)
            return await self.start_monitor()
        else:
            return stop_result

    async def _wait_for_process(self):
        """Асинхронно чекає завершення процесу"""
        while self.process and self.process.poll() is None:
            await asyncio.sleep(0.1)

    async def _read_logs_async(self):
        """Асинхронно читає логи процесу"""
        global monitor_logs

        try:
            logger.info("📝 Початок читання логів...")

            while self.process and self.process.poll() is None:
                # Асинхронно читаємо вихід процесу
                line = await asyncio.create_task(
                    asyncio.to_thread(self.process.stdout.readline)
                )

                if line:
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    log_entry = f"[{timestamp}] {line.strip()}"
                    monitor_logs.append(log_entry)

                    # Обмежуємо кількість логів
                    if len(monitor_logs) > max_log_lines:
                        monitor_logs = monitor_logs[-max_log_lines:]

                    # Асинхронно записуємо в файл
                    await self._write_log_to_file_async(log_entry)

                    # Логуємо в консоль (опціонально)
                    logger.debug(f"LOG: {log_entry}")

                # Невелика пауза щоб не блокувати event loop
                await asyncio.sleep(0.01)

        except asyncio.CancelledError:
            logger.info("📝 Читання логів скасовано")
            raise
        except Exception as e:
            error_msg = f"[ERROR] Помилка читання логів: {str(e)}"
            monitor_logs.append(error_msg)
            logger.error(error_msg)

    async def _write_log_to_file_async(self, log_entry: str):
        """Асинхронно записує лог у файл"""
        try:
            await asyncio.to_thread(self._write_log_sync, log_entry)
        except Exception as e:
            logger.error(f"Помилка запису логу: {e}")

    def _write_log_sync(self, log_entry: str):
        """Синхронний запис логу (викликається в окремому потоці)"""
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"{log_entry}\n")
                f.flush()
        except Exception:
            pass  # Ігноруємо помилки запису

    async def get_logs(self, last_n: int = 50) -> Dict[str, Any]:
        """Повертає останні N логів"""
        global monitor_logs
        return {"logs": monitor_logs[-last_n:]}

    async def clear_logs(self) -> Dict[str, Any]:
        """Очищає логи"""
        global monitor_logs
        monitor_logs = []
        return {"success": True, "message": "Логи очищено"}

    async def get_log_file_content(self) -> str:
        """Асинхронно читає вміст лог файлу"""
        try:
            content = await asyncio.to_thread(self._read_log_file_sync)
            return content
        except Exception as e:
            return f"Помилка читання файлу логів: {str(e)}"

    def _read_log_file_sync(self) -> str:
        """Синхронне читання лог файлу"""
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return "Файл логів не знайдено"
        except Exception as e:
            return f"Помилка: {str(e)}"


# Ініціалізуємо контролер
controller = AsyncMonitorController()

# FastAPI endpoints з async/await
from fastapi import FastAPI

app = FastAPI(title="Async Telegram Monitor Control Panel")


@app.post("/api/monitor/start")
async def start_monitor():
    """Асинхронний запуск моніторингу"""
    return await controller.start_monitor()


@app.post("/api/monitor/stop")
async def stop_monitor():
    """Асинхронна зупинка моніторингу"""
    return await controller.stop_monitor()


@app.post("/api/monitor/restart")
async def restart_monitor():
    """Асинхронний перезапуск моніторингу"""
    return await controller.restart_monitor()


@app.get("/api/monitor/status")
async def get_monitor_status():
    """Отримання статусу моніторингу"""
    return controller.get_status()


@app.get("/api/monitor/logs")
async def get_logs():
    """Отримання логів"""
    return await controller.get_logs()


@app.post("/api/monitor/logs/clear")
async def clear_logs():
    """Очищення логів"""
    return await controller.clear_logs()


@app.get("/api/monitor/logs/file")
async def get_log_file():
    """Отримання вмісту лог файлу"""
    content = await controller.get_log_file_content()
    return {"content": content}


# Graceful shutdown
import signal
import sys


async def shutdown_handler():
    """Обробник graceful shutdown"""
    logger.info("🛑 Отримано сигнал завершення, зупиняю моніторинг...")
    await controller.stop_monitor()
    logger.info("✅ Моніторинг зупинено, завершення роботи")


def signal_handler(signum, frame):
    """Обробник системних сигналів"""
    logger.info(f"Отримано сигнал {signum}")
    asyncio.create_task(shutdown_handler())


# Реєструємо обробники сигналів
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

if __name__ == "__main__":
    import uvicorn

    print("🤖 Async Telegram Monitor - Control Panel")
    print("=" * 60)
    print(f"📅 Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"👤 Користувач: SergZels")
    print("🔄 Режим: Асинхронний")
    print("")
    print("🎛️  Функціональність:")
    print("   ⚡ Асинхронне управління процесами")
    print("   📝 Асинхронне читання логів")
    print("   🔄 Non-blocking операції")
    print("   ⚙️ Graceful shutdown")
    print("")
    print("🚀 Запуск Async Control Panel...")
    print("🌐 Відкрийте у браузері: http://localhost:8080")
    print("⏹️  Зупинити: Ctrl+C")
    print("=" * 60)

    # Запускаємо з налаштуваннями для async
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080,
        loop="asyncio",  # Використовуємо asyncio event loop
        log_level="info"
    )