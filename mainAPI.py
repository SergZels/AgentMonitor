from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
from fastapi.responses import HTMLResponse, StreamingResponse
import json
import os
from fastapi.security import APIKeyQuery
import psutil
import asyncio
from datetime import datetime
from typing import  Dict, Any
from main import main
import logging

app = FastAPI(title="Telegram Monitor Control Panel")

# Глобальні змінні для контролю процесу
monitor_logs = []
max_log_lines = 100


class AsyncLogHandler(logging.Handler):
    """Кастомний хендлер для перехоплення логів"""

    def __init__(self, log_callback):
        super().__init__()
        self.log_callback = log_callback

    def emit(self, record):
        try:
            msg = self.format(record)
            self.log_callback(msg)
        except Exception:
            pass


class MonitorController:
    def __init__(self):
        self.task = None
        self.status = "stopped"
        self.start_time = None
        self.log_handler = None
        self._setup_logging()

    def _setup_logging(self):
        """Налаштування перехоплення логів"""
        self.log_handler = AsyncLogHandler(self._add_log)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        self.log_handler.setFormatter(formatter)

        # Додаємо хендлер до root logger
        root_logger = logging.getLogger()
        root_logger.addHandler(self.log_handler)
        root_logger.setLevel(logging.INFO)

    def _add_log(self, message):
        """Додає повідомлення до логів"""
        global monitor_logs
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        monitor_logs.append(log_entry)

        # Обмежуємо кількість логів
        if len(monitor_logs) > max_log_lines:
            monitor_logs = monitor_logs[-max_log_lines:]

    def get_status(self):
        if self.task and not self.task.done():
            return {
                "status": "running",
                "task_id": id(self.task),
                "start_time": self.start_time.isoformat() if self.start_time else None,
                "uptime": str(datetime.now() - self.start_time)
                if self.start_time
                else None,
            }
        else:
            return {
                "status": "stopped",
                "task_id": None,
                "start_time": None,
                "uptime": None,
            }

    async def start_monitor(self):
        """Асинхронний запуск моніторингу"""
        if self.task and not self.task.done():
            return {"success": False, "message": "Моніторинг вже запущено"}

        try:
            # Просто створюємо task в поточному event loop
            self.task = asyncio.create_task(self._run_monitor())
            self.start_time = datetime.now()

            self._add_log(f"Моніторинг запущено (Task ID: {id(self.task)})")

            return {
                "success": True,
                "message": f"Моніторинг запущено (Task ID: {id(self.task)})",
                "task_id": id(self.task),
            }

        except Exception as e:
            self._add_log(f"Помилка запуску: {str(e)}")
            return {"success": False, "message": f"Помилка запуску: {str(e)}"}

    async def _run_monitor(self):
        """Запускає основну корутину з обробкою помилок"""
        try:
            self._add_log("Запуск основної корутини main()")
            await main()
        except asyncio.CancelledError:
            self._add_log("Моніторинг було скасовано")
            raise
        except Exception as e:
            self._add_log(f"Помилка в main(): {str(e)}")
            raise
        finally:
            self._add_log("Завершення роботи корутини main()")

    async def stop_monitor(self):
        """Асинхронна зупинка моніторингу"""
        if not self.task or self.task.done():
            return {"success": False, "message": "Моніторинг не запущено"}

        try:
            task_id = id(self.task)

            # Скасовуємо задачу
            self.task.cancel()

            # Чекаємо завершення задачі з timeout
            try:
                await asyncio.wait_for(self.task, timeout=10)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

            self.task = None
            self.start_time = None

            self._add_log(f"Моніторинг зупинено (Task ID: {task_id})")

            return {
                "success": True,
                "message": f"Моніторинг зупинено (Task ID: {task_id})",
            }

        except Exception as e:
            self._add_log(f"Помилка зупинки: {str(e)}")
            return {"success": False, "message": f"Помилка зупинки: {str(e)}"}

    async def restart_monitor(self):
        """Асинхронний перезапуск моніторингу"""
        self._add_log("Перезапуск моніторингу...")
        stop_result = await self.stop_monitor()
        if stop_result["success"] or "не запущено" in stop_result["message"]:
            await asyncio.sleep(2)  # Коротка пауза
            return await self.start_monitor()
        else:
            return stop_result

    def get_logs(self, lines=None):
        """Повертає останні логи"""
        global monitor_logs
        if lines:
            return monitor_logs[-lines:]
        return monitor_logs

    def clear_logs(self):
        """Очищає логи"""
        global monitor_logs
        monitor_logs = []
        self._add_log("Логи очищено")

    def __del__(self):
        """Очищення при видаленні об'єкта"""
        if self.log_handler:
            logging.getLogger().removeHandler(self.log_handler)


controller = MonitorController()
api_key_query = APIKeyQuery(name="password", auto_error=False)

def get_password(password: str = Depends(api_key_query)):
    if password != "5555$zR@l5":
        raise HTTPException(
            status_code=401,
            detail="Invalid password",
        )
    return password

# Решта коду для HTML та API залишається такою ж...

@app.get("/", response_class=HTMLResponse)
async def get_config_page(password: str = Depends(get_password)):
    return HTMLResponse(content=get_html_content())

@app.get("/api/config")
async def get_config():
    try:
        if not os.path.exists("config.json"):
            return {
                "error": "Файл config.json не знайдено",
                "template": {
                    "telegram": {"api_id": 0, "api_hash": "", "session_string": ""},
                    "global_settings": {
                        "check_interval_seconds": 60,
                        "notification_user_id": "me",
                        "timezone": "Europe/Kiev",
                        "night_hours": {"start": "22:00", "end": "08:00"},
                    },
                    "groups": [],
                },
            }

        with open("config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
        return config

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Помилка читання: {str(e)}")

@app.post("/api/config")
async def save_config(config: Dict[str, Any]):
    try:
        if os.path.exists("config.json"):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            import shutil
            shutil.copy("config.json", f"config_backup_{timestamp}.json")

        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        return {
            "status": "success",
            "message": f"Конфігурацію збережено: {len(config.get('groups', []))} груп",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Помилка збереження: {str(e)}")

# API для управління моніторингом - тепер всі асинхронні
@app.post("/api/monitor/start")
async def start_monitor():
    return await controller.start_monitor()

@app.post("/api/monitor/stop")
async def stop_monitor():
    return await controller.stop_monitor()

@app.post("/api/monitor/restart")
async def restart_monitor():
    return await controller.restart_monitor()

@app.get("/api/monitor/status")
async def get_monitor_status():
    return controller.get_status()

@app.get("/api/monitor/logs")
async def get_logs():
    global monitor_logs
    return {"logs": monitor_logs[-50:]}

@app.post("/api/monitor/logs/clear")
async def clear_logs():
    controller.clear_logs()
    return {"success": True}

@app.get("/api/monitor/logs/download")
async def download_logs():
    global monitor_logs

    def generate_log_file():
        yield f"# Telegram Monitor Logs - {datetime.now()}\n"
        for log in monitor_logs:
            yield f"{log}\n"

    return StreamingResponse(
        generate_log_file(),
        media_type="text/plain",
        headers={
            "Content-Disposition": f"attachment; filename=monitor_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        },
    )

@app.get("/api/system/info")
async def get_system_info():
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()

        python_processes = 0
        for proc in psutil.process_iter(["name"]):
            try:
                if "python" in proc.info["name"].lower():
                    python_processes += 1
            except:
                pass

        return {
            "cpu_percent": cpu_percent,
            "memory_percent": memory.percent,
            "python_processes": python_processes,
            "total_memory_gb": round(memory.total / (1024**3), 2),
            "available_memory_gb": round(memory.available / (1024**3), 2),
        }
    except Exception as e:
        return {
            "cpu_percent": 0,
            "memory_percent": 0,
            "python_processes": 0,
            "error": str(e),
        }

# HTML функція залишається така ж...
def get_html_content():
    """Розширений HTML з панеллю управління"""
    try:
        with open("config_editor.html", "r", encoding="utf-8") as f:
            html_content = f.read()

        # Вставляємо поточні дані
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        html_content = html_content.replace(
            '<span class="badge bg-secondary">2025-06-02 14:07:23 UTC</span>',
            f'<span class="badge bg-secondary">{current_time}</span>',
        )

        # Додаємо панель управління після заголовка
        control_panel = """
                <!-- Панель управління моніторингом -->
                <div class="config-section" id="control-panel">
                    <div class="section-header d-flex justify-content-between align-items-center">
                        <h4><i class="fas fa-play-circle"></i> Управління Моніторингом</h4>
                        <div id="monitor-status-badge"></div>
                    </div>

                    <div class="row">
                        <div class="col-md-8">
                            <div class="d-flex gap-2 mb-3">
                                <button class="btn btn-success" onclick="startMonitor()" id="start-btn">
                                    <i class="fas fa-play"></i> Запустити
                                </button>
                                <button class="btn btn-danger" onclick="stopMonitor()" id="stop-btn">
                                    <i class="fas fa-stop"></i> Зупинити
                                </button>
                                <button class="btn btn-warning" onclick="restartMonitor()" id="restart-btn">
                                    <i class="fas fa-redo"></i> Перезапустити
                                </button>
                                <button class="btn btn-info" onclick="checkStatus()" id="status-btn">
                                    <i class="fas fa-refresh"></i> Статус
                                </button>
                            </div>

                            <div id="monitor-info" class="mb-3"></div>
                        </div>

                        <div class="col-md-4">
                            <div class="bg-dark text-light rounded p-2">
                                <small><strong>Системна інформація:</strong></small>
                                <div id="system-info" style="font-size: 0.8em;">
                                    <div>CPU: <span id="cpu-usage">-</span>%</div>
                                    <div>RAM: <span id="ram-usage">-</span>%</div>
                                    <div>Процеси Python: <span id="python-processes">-</span></div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Логи в реальному часі -->
                    <div class="mt-3">
                        <div class="d-flex justify-content-between align-items-center mb-2">
                            <h6><i class="fas fa-terminal"></i> Логи Моніторингу</h6>
                            <div>
                                <button class="btn btn-sm btn-outline-secondary" onclick="clearLogs()">
                                    <i class="fas fa-trash"></i> Очистити
                                </button>
                                <button class="btn btn-sm btn-outline-info" onclick="downloadLogs()">
                                    <i class="fas fa-download"></i> Завантажити
                                </button>
                            </div>
                        </div>
                        <div id="logs-container" class="bg-dark text-light rounded p-3" style="height: 300px; overflow-y: auto; font-family: 'Courier New', monospace; font-size: 0.85em;">
                            <div id="logs-content">Логи з'являться тут...</div>
                        </div>
                    </div>
                </div>
        """

        # Вставляємо панель після заголовка
        html_content = html_content.replace(
            "</div>\n\n                <!-- Telegram API секція -->",
            f"</div>\n\n{control_panel}\n\n                <!-- Telegram API секція -->",
        )

        # Додаємо JavaScript для управління
        monitor_js = """
        // Управління моніторингом
        let statusInterval;

        async function startMonitor() {
            try {
                showToast('Запуск моніторингу...', 'info');
                const response = await fetch('/api/monitor/start', { method: 'POST' });
                const result = await response.json();

                if (result.success) {
                    showToast(result.message, 'success');
                    startStatusUpdates();
                } else {
                    showToast(result.message, 'danger');
                }

                checkStatus();
            } catch (error) {
                showToast('Помилка запуску: ' + error.message, 'danger');
            }
        }

        async function stopMonitor() {
            try {
                showToast('Зупинка моніторингу...', 'warning');
                const response = await fetch('/api/monitor/stop', { method: 'POST' });
                const result = await response.json();

                if (result.success) {
                    showToast(result.message, 'success');
                    stopStatusUpdates();
                } else {
                    showToast(result.message, 'danger');
                }

                checkStatus();
            } catch (error) {
                showToast('Помилка зупинки: ' + error.message, 'danger');
            }
        }

        async function restartMonitor() {
            try {
                showToast('Перезапуск моніторингу...', 'warning');
                const response = await fetch('/api/monitor/restart', { method: 'POST' });
                const result = await response.json();

                if (result.success) {
                    showToast(result.message, 'success');
                    startStatusUpdates();
                } else {
                    showToast(result.message, 'danger');
                }

                checkStatus();
            } catch (error) {
                showToast('Помилка перезапуску: ' + error.message, 'danger');
            }
        }

        async function checkStatus() {
            try {
                const response = await fetch('/api/monitor/status');
                const status = await response.json();
                updateStatusDisplay(status);

                // Оновлюємо системну інформацію
                const sysResponse = await fetch('/api/system/info');
                const sysInfo = await sysResponse.json();
                updateSystemInfo(sysInfo);

            } catch (error) {
                console.error('Помилка отримання статусу:', error);
            }
        }

        function updateStatusDisplay(status) {
            const badge = document.getElementById('monitor-status-badge');
            const info = document.getElementById('monitor-info');

            if (status.status === 'running') {
                badge.innerHTML = '<span class="badge bg-success"><i class="fas fa-play"></i> Запущено</span>';
                info.innerHTML = `
                    <div class="alert alert-success">
                        <strong><i class="fas fa-check-circle"></i> Моніторинг активний</strong><br>
                        <small>PID: ${status.pid} | Запущено: ${status.start_time} | Час роботи: ${status.uptime}</small>
                    </div>
                `;

                document.getElementById('start-btn').disabled = true;
                document.getElementById('stop-btn').disabled = false;
                document.getElementById('restart-btn').disabled = false;
            } else {
                badge.innerHTML = '<span class="badge bg-danger"><i class="fas fa-stop"></i> Зупинено</span>';
                info.innerHTML = `
                    <div class="alert alert-secondary">
                        <strong><i class="fas fa-pause-circle"></i> Моніторинг не активний</strong><br>
                        <small>Натисніть "Запустити" для початку моніторингу</small>
                    </div>
                `;

                document.getElementById('start-btn').disabled = false;
                document.getElementById('stop-btn').disabled = true;
                document.getElementById('restart-btn').disabled = true;
            }
        }

        function updateSystemInfo(info) {
            document.getElementById('cpu-usage').textContent = info.cpu_percent.toFixed(1);
            document.getElementById('ram-usage').textContent = info.memory_percent.toFixed(1);
            document.getElementById('python-processes').textContent = info.python_processes;
        }

        async function updateLogs() {
            try {
                const response = await fetch('/api/monitor/logs');
                const logs = await response.json();

                const logsContent = document.getElementById('logs-content');
                if (logs.logs && logs.logs.length > 0) {
                    logsContent.innerHTML = logs.logs.join('<br>');
                    // Автоскрол вниз
                    const container = document.getElementById('logs-container');
                    container.scrollTop = container.scrollHeight;
                }
            } catch (error) {
                console.error('Помилка отримання логів:', error);
            }
        }

        function startStatusUpdates() {
            if (statusInterval) clearInterval(statusInterval);
            statusInterval = setInterval(() => {
                checkStatus();
                updateLogs();
            }, 3000); // Оновлюємо кожні 3 секунди
        }

        function stopStatusUpdates() {
            if (statusInterval) {
                clearInterval(statusInterval);
                statusInterval = null;
            }
        }

        function clearLogs() {
            fetch('/api/monitor/logs/clear', { method: 'POST' })
                .then(() => {
                    document.getElementById('logs-content').innerHTML = 'Логи очищено...';
                    showToast('Логи очищено', 'info');
                });
        }

        function downloadLogs() {
            window.open('/api/monitor/logs/download', '_blank');
        }

        // Запускаємо перевірку статусу при завантаженні сторінки
        document.addEventListener('DOMContentLoaded', function() {
            checkStatus();
            updateLogs();
            startStatusUpdates();
        });
        """

        # Додаємо JavaScript в кінець
        html_content = html_content.replace(
            "</script>\n</body>", f"{monitor_js}\n        </script>\n</body>"
        )

        return html_content

    except FileNotFoundError:
        return get_error_html()

def get_error_html():
    return """
    <html><body style="font-family: Arial; padding: 20px;">
    <h1>❌ Помилка завантаження</h1>
    <p>Файл config_editor.html не знайдено!</p>
    <p>Створіть файл з попереднього коду або перевірте шлях до файлу.</p>
    </body></html>
    """

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)