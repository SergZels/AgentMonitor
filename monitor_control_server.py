from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
import json
import os
import subprocess
import psutil
import asyncio
from datetime import datetime
from typing import List, Dict, Optional, Any
import threading
import time
import sys
import signal

app = FastAPI(title="Telegram Monitor Control Panel")

# Глобальні змінні
monitor_logs = []
max_log_lines = 200


class DockerMonitorController:
    def __init__(self):
        self.process = None
        self.status = "stopped"
        self.start_time = None

        # В Docker завжди використовуємо поточний Python
        self.python_executable = sys.executable

        # Створюємо необхідні директорії
        self.ensure_directories()

    def ensure_directories(self):
        """Створює необхідні директорії"""
        dirs = ["/app/logs", "/app/data", "/app/config", "/app/backups"]
        for dir_path in dirs:
            os.makedirs(dir_path, exist_ok=True)

    def get_status(self):
        if self.process and self.process.poll() is None:
            return {
                "status": "running",
                "pid": self.process.pid,
                "start_time": self.start_time.isoformat() if self.start_time else None,
                "uptime": str(datetime.now() - self.start_time)
                if self.start_time
                else None,
                "container_id": os.environ.get("HOSTNAME", "unknown"),
            }
        else:
            return {
                "status": "stopped",
                "pid": None,
                "start_time": None,
                "uptime": None,
                "container_id": os.environ.get("HOSTNAME", "unknown"),
            }

    def get_docker_info(self):
        """Отримує інформацію про Docker контейнер"""
        try:
            return {
                "success": True,
                "python_version": sys.version,
                "python_path": sys.executable,
                "container_id": os.environ.get("HOSTNAME", "unknown"),
                "timezone": os.environ.get("TZ", "UTC"),
                "working_directory": os.getcwd(),
                "user": os.environ.get("USER", "unknown"),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def start_monitor(self):
        if self.process and self.process.poll() is None:
            return {"success": False, "message": "Моніторинг вже запущено"}

        try:
            print(f"🚀 Запускаю моніторинг в Docker контейнері")

            # Перевіряємо наявність main.py
            if not os.path.exists("/app/main.py"):
                return {"success": False, "message": "Файл main.py не знайдено в /app/"}

            # Запускаємо основний скрипт
            self.process = subprocess.Popen(
                [self.python_executable, "/app/main.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
                cwd="/app",
            )

            self.start_time = datetime.now()

            # Запускаємо читання логів
            threading.Thread(target=self._read_logs, daemon=True).start()

            return {
                "success": True,
                "message": f"Моніторинг запущено в контейнері (PID: {self.process.pid})",
                "pid": self.process.pid,
                "container_id": os.environ.get("HOSTNAME", "unknown"),
            }

        except Exception as e:
            return {"success": False, "message": f"Помилка запуску: {str(e)}"}

    def stop_monitor(self):
        if not self.process or self.process.poll() is not None:
            return {"success": False, "message": "Моніторинг не запущено"}

        try:
            pid = self.process.pid

            # Graceful shutdown
            self.process.terminate()

            # Чекаємо 15 секунд
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                print("⚠️ Примусове завершення процесу")
                self.process.kill()
                self.process.wait()

            self.process = None
            self.start_time = None

            return {"success": True, "message": f"Моніторинг зупинено (PID: {pid})"}

        except Exception as e:
            return {"success": False, "message": f"Помилка зупинки: {str(e)}"}

    def restart_monitor(self):
        stop_result = self.stop_monitor()
        if stop_result["success"] or "не запущено" in stop_result["message"]:
            time.sleep(3)  # Пауза для Docker
            return self.start_monitor()
        else:
            return stop_result

    def _read_logs(self):
        """Читає логи процесу в реальному часі"""
        global monitor_logs
        try:
            while self.process and self.process.poll() is None:
                line = self.process.stdout.readline()
                if line:
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    log_entry = f"[{timestamp}] {line.strip()}"
                    monitor_logs.append(log_entry)

                    # Обмежуємо кількість логів
                    if len(monitor_logs) > max_log_lines:
                        monitor_logs = monitor_logs[-max_log_lines:]

                    # Зберігаємо в файл
                    try:
                        with open("/app/logs/monitor.log", "a", encoding="utf-8") as f:
                            f.write(f"{log_entry}\n")
                    except:
                        pass

        except Exception as e:
            error_msg = f"[ERROR] Помилка читання логів: {str(e)}"
            monitor_logs.append(error_msg)
            print(error_msg)


# Ініціалізуємо контролер
controller = DockerMonitorController()


# Обробник для graceful shutdown
def signal_handler(signum, frame):
    print(f"\n🛑 Отримано сигнал {signum}, зупиняю моніторинг...")
    controller.stop_monitor()
    sys.exit(0)


signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


@app.get("/", response_class=HTMLResponse)
async def get_config_page():
    """Головна сторінка з Docker-оптимізованим інтерфейсом"""
    docker_html = f"""
<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Telegram Monitor - Docker Control Panel</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        .container-info {{ background: linear-gradient(45deg, #0074D9, #001f3f); color: white; }}
        .logs-container {{ background: #1a1a1a; color: #00ff00; font-family: 'Courier New', monospace; }}
    </style>
</head>
<body class="bg-light">
    <div class="container-fluid py-4">
        <!-- Заголовок з Docker інформацією -->
        <div class="container-info rounded p-3 mb-4">
            <div class="row align-items-center">
                <div class="col-md-8">
                    <h1 class="mb-1"><i class="fab fa-docker"></i> Telegram Monitor - Docker Control Panel</h1>
                    <small>Контейнер: {os.environ.get("HOSTNAME", "unknown")} | Користувач: SergZels | Дата: {datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")}</small>
                </div>
                <div class="col-md-4 text-end">
                    <span class="badge bg-success fs-6"><i class="fas fa-check-circle"></i> Docker Ready</span>
                </div>
            </div>
        </div>

        <div class="row">
            <div class="col-lg-8">
                <!-- Панель управління -->
                <div class="card mb-4">
                    <div class="card-header bg-primary text-white">
                        <h4 class="mb-0"><i class="fas fa-play-circle"></i> Управління Моніторингом</h4>
                    </div>
                    <div class="card-body">
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
                                <i class="fas fa-refresh"></i> Оновити статус
                            </button>
                            <button class="btn btn-secondary" onclick="downloadLogs()">
                                <i class="fas fa-download"></i> Завантажити логи
                            </button>
                        </div>

                        <div id="status-display" class="alert alert-secondary">
                            <div class="d-flex justify-content-between align-items-center">
                                <span>Натисніть "Оновити статус" для перевірки</span>
                                <div class="spinner-border spinner-border-sm d-none" id="loading-spinner"></div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Логи -->
                <div class="card">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h5 class="mb-0"><i class="fas fa-terminal"></i> Логи Моніторингу</h5>
                        <div>
                            <button class="btn btn-sm btn-outline-danger" onclick="clearLogs()">
                                <i class="fas fa-trash"></i> Очистити
                            </button>
                            <button class="btn btn-sm btn-outline-secondary" onclick="toggleAutoUpdate()">
                                <i class="fas fa-sync-alt"></i> <span id="auto-update-text">Авто-оновлення</span>
                            </button>
                        </div>
                    </div>
                    <div class="card-body p-0">
                        <div class="logs-container p-3" style="height: 400px; overflow-y: auto;">
                            <div id="logs-content">Логи з'являться тут...</div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="col-lg-4">
                <!-- Docker інформація -->
                <div class="card mb-4">
                    <div class="card-header">
                        <h5 class="mb-0"><i class="fab fa-docker"></i> Docker Інформація</h5>
                    </div>
                    <div class="card-body">
                        <div id="docker-info">Завантаження...</div>
                    </div>
                </div>

                <!-- Системна інформація -->
                <div class="card mb-4">
                    <div class="card-header">
                        <h5 class="mb-0"><i class="fas fa-server"></i> Система</h5>
                    </div>
                    <div class="card-body">
                        <div id="system-info">
                            <div>CPU: <span id="cpu-usage">-</span>%</div>
                            <div>RAM: <span id="ram-usage">-</span>%</div>
                            <div>Python процеси: <span id="python-processes">-</span></div>
                        </div>
                    </div>
                </div>

                <!-- Конфігурація -->
                <div class="card">
                    <div class="card-header">
                        <h5 class="mb-0"><i class="fas fa-cog"></i> Швидкі дії</h5>
                    </div>
                    <div class="card-body">
                        <div class="d-grid gap-2">
                            <button class="btn btn-outline-primary" onclick="window.open('/api/config', '_blank')">
                                <i class="fas fa-eye"></i> Переглянути config.json
                            </button>
                            <button class="btn btn-outline-secondary" onclick="showContainerLogs()">
                                <i class="fas fa-file-alt"></i> Логи контейнера
                            </button>
                            <button class="btn btn-outline-info" onclick="restartContainer()" disabled>
                                <i class="fas fa-refresh"></i> Перезапустити контейнер
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        let autoUpdateInterval;
        let isAutoUpdating = true;

        function showLoading(show = true) {{
            const spinner = document.getElementById('loading-spinner');
            if (show) {{
                spinner.classList.remove('d-none');
            }} else {{
                spinner.classList.add('d-none');
            }}
        }}

        function showToast(message, type = 'info') {{
            // Простий toast для Docker
            const toast = document.createElement('div');
            toast.className = `alert alert-${{type}} position-fixed`;
            toast.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
            toast.innerHTML = `
                ${{message}}
                <button type="button" class="btn-close" onclick="this.parentElement.remove()"></button>
            `;
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 5000);
        }}

        async function startMonitor() {{
            showLoading();
            try {{
                const response = await fetch('/api/monitor/start', {{ method: 'POST' }});
                const result = await response.json();
                showToast(result.message, result.success ? 'success' : 'danger');
                await checkStatus();
            }} catch (error) {{
                showToast('Помилка запуску: ' + error.message, 'danger');
            }}
            showLoading(false);
        }}

        async function stopMonitor() {{
            showLoading();
            try {{
                const response = await fetch('/api/monitor/stop', {{ method: 'POST' }});
                const result = await response.json();
                showToast(result.message, result.success ? 'success' : 'danger');
                await checkStatus();
            }} catch (error) {{
                showToast('Помилка зупинки: ' + error.message, 'danger');
            }}
            showLoading(false);
        }}

        async function restartMonitor() {{
            showLoading();
            try {{
                const response = await fetch('/api/monitor/restart', {{ method: 'POST' }});
                const result = await response.json();
                showToast(result.message, result.success ? 'success' : 'danger');
                await checkStatus();
            }} catch (error) {{
                showToast('Помилка перезапуску: ' + error.message, 'danger');
            }}
            showLoading(false);
        }}

        async function checkStatus() {{
            try {{
                const [statusResponse, systemResponse, dockerResponse] = await Promise.all([
                    fetch('/api/monitor/status'),
                    fetch('/api/system/info'),
                    fetch('/api/docker/info')
                ]);

                const status = await statusResponse.json();
                const systemInfo = await systemResponse.json();
                const dockerInfo = await dockerResponse.json();

                updateStatusDisplay(status);
                updateSystemInfo(systemInfo);
                updateDockerInfo(dockerInfo);

            }} catch (error) {{
                console.error('Помилка отримання статусу:', error);
            }}
        }}

        function updateStatusDisplay(status) {{
            const statusDiv = document.getElementById('status-display');

            if (status.status === 'running') {{
                statusDiv.className = 'alert alert-success';
                statusDiv.innerHTML = `
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <strong><i class="fas fa-check-circle"></i> Моніторинг активний</strong><br>
                            <small>PID: ${{status.pid}} | Запущено: ${{status.start_time}} | Час роботи: ${{status.uptime}}</small><br>
                            <small>Контейнер: ${{status.container_id}}</small>
                        </div>
                        <span class="badge bg-success">RUNNING</span>
                    </div>
                `;

                document.getElementById('start-btn').disabled = true;
                document.getElementById('stop-btn').disabled = false;
                document.getElementById('restart-btn').disabled = false;
            }} else {{
                statusDiv.className = 'alert alert-secondary';
                statusDiv.innerHTML = `
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <strong><i class="fas fa-pause-circle"></i> Моніторинг не активний</strong><br>
                            <small>Натисніть "Запустити" для початку роботи</small>
                        </div>
                        <span class="badge bg-secondary">STOPPED</span>
                    </div>
                `;

                document.getElementById('start-btn').disabled = false;
                document.getElementById('stop-btn').disabled = true;
                document.getElementById('restart-btn').disabled = true;
            }}
        }}

        function updateSystemInfo(info) {{
            document.getElementById('cpu-usage').textContent = info.cpu_percent?.toFixed(1) || '-';
            document.getElementById('ram-usage').textContent = info.memory_percent?.toFixed(1) || '-';
            document.getElementById('python-processes').textContent = info.python_processes || '-';
        }}

        function updateDockerInfo(info) {{
            const container = document.getElementById('docker-info');
            if (info.success) {{
                container.innerHTML = `
                    <small>
                        <div><strong>Python:</strong> ${{info.python_version.split(' ')[0]}}</div>
                        <div><strong>Контейнер:</strong> ${{info.container_id}}</div>
                        <div><strong>Часова зона:</strong> ${{info.timezone}}</div>
                        <div><strong>Користувач:</strong> ${{info.user}}</div>
                    </small>
                `;
            }} else {{
                container.innerHTML = `<small class="text-danger">Помилка: ${{info.error}}</small>`;
            }}
        }}

        async function updateLogs() {{
            try {{
                const response = await fetch('/api/monitor/logs');
                const logs = await response.json();
                const logsContent = document.getElementById('logs-content');

                if (logs.logs && logs.logs.length > 0) {{
                    logsContent.innerHTML = logs.logs.join('<br>');
                    // Автоскрол вниз
                    const container = logsContent.parentElement;
                    container.scrollTop = container.scrollHeight;
                }}
            }} catch (error) {{
                console.error('Помилка отримання логів:', error);
            }}
        }}

        async function clearLogs() {{
            try {{
                await fetch('/api/monitor/logs/clear', {{ method: 'POST' }});
                document.getElementById('logs-content').innerHTML = 'Логи очищено...';
                showToast('Логи очищено', 'info');
            }} catch (error) {{
                showToast('Помилка очищення логів: ' + error.message, 'danger');
            }}
        }}

        function downloadLogs() {{
            window.open('/api/monitor/logs/download', '_blank');
        }}

        function toggleAutoUpdate() {{
            isAutoUpdating = !isAutoUpdating;
            const button = document.getElementById('auto-update-text');

            if (isAutoUpdating) {{
                startAutoUpdate();
                button.textContent = 'Авто-оновлення ВКЛ';
                showToast('Авто-оновлення увімкнено', 'info');
            }} else {{
                stopAutoUpdate();
                button.textContent = 'Авто-оновлення ВИКЛ';
                showToast('Авто-оновлення вимкнено', 'warning');
            }}
        }}

        function startAutoUpdate() {{
            if (autoUpdateInterval) clearInterval(autoUpdateInterval);
            autoUpdateInterval = setInterval(() => {{
                checkStatus();
                updateLogs();
            }}, 3000);
        }}

        function stopAutoUpdate() {{
            if (autoUpdateInterval) {{
                clearInterval(autoUpdateInterval);
                autoUpdateInterval = null;
            }}
        }}

        function showContainerLogs() {{
            showToast('Використайте: docker logs telegram_monitor_control', 'info');
        }}

        // Ініціалізація при завантаженні
        document.addEventListener('DOMContentLoaded', function() {{
            checkStatus();
            updateLogs();
            startAutoUpdate();
        }});

        // Обробка помилок
        window.addEventListener('error', function(e) {{
            console.error('JavaScript помилка:', e.error);
        }});
    </script>
</body>
</html>
    """
    return HTMLResponse(content=docker_html)


# API endpoints
@app.get("/api/config")
async def get_config():
    config_paths = ["/app/config.json", "/app/config/config.json"]

    for config_path in config_paths:
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                continue

    return {
        "error": "config.json не знайдено",
        "message": "Помістіть config.json в /app/ або /app/config/",
    }


@app.post("/api/config")
async def save_config(config: Dict[str, Any]):
    try:
        config_path = "/app/config.json"

        # Backup
        if os.path.exists(config_path):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"/app/backups/config_backup_{timestamp}.json"
            import shutil

            shutil.copy(config_path, backup_path)

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        return {
            "status": "success",
            "message": "Конфігурацію збережено в Docker контейнері",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Помилка збереження: {str(e)}")


@app.post("/api/monitor/start")
async def start_monitor():
    return controller.start_monitor()


@app.post("/api/monitor/stop")
async def stop_monitor():
    return controller.stop_monitor()


@app.post("/api/monitor/restart")
async def restart_monitor():
    return controller.restart_monitor()


@app.get("/api/monitor/status")
async def get_monitor_status():
    return controller.get_status()


@app.get("/api/monitor/logs")
async def get_logs():
    global monitor_logs
    return {"logs": monitor_logs[-100:]}


@app.post("/api/monitor/logs/clear")
async def clear_logs():
    global monitor_logs
    monitor_logs = []
    return {"success": True}


@app.get("/api/monitor/logs/download")
async def download_logs():
    def generate_log_file():
        yield f"# Telegram Monitor Docker Logs - {datetime.now()}\n"
        yield f"# Container: {os.environ.get('HOSTNAME', 'unknown')}\n"
        yield f"# User: SergZels\n\n"
        for log in monitor_logs:
            yield f"{log}\n"

    return StreamingResponse(
        generate_log_file(),
        media_type="text/plain",
        headers={
            "Content-Disposition": f"attachment; filename=docker_monitor_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        },
    )


@app.get("/api/docker/info")
async def get_docker_info():
    return controller.get_docker_info()


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
        }
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    import uvicorn

    print("🐳 Telegram Monitor - Docker Control Panel")
    print("=" * 60)
    print(f"📅 Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"👤 Користувач: SergZels")
    print(f"🐳 Контейнер: {os.environ.get('HOSTNAME', 'unknown')}")
    print(f"📁 Робоча директорія: {os.getcwd()}")
    print(f"🌍 Часова зона: {os.environ.get('TZ', 'UTC')}")

    # Перевіряємо файли
    files = {
        "/app/main.py": os.path.exists("/app/main.py"),
        "/app/config.json": os.path.exists("/app/config.json"),
        "/app/config/config.json": os.path.exists("/app/config/config.json"),
    }

    print("\n📋 Статус файлів:")
    for file, exists in files.items():
        status = "✅" if exists else "❌"
        print(f"   {file}: {status}")

    controller.ensure_directories()

    print("\n🎛️  Docker функціональність:")
    print("   ⚙️  Веб-управління конфігурацією")
    print("   ▶️  Запуск/зупинка моніторингу")
    print("   📊 Real-time логи та статистика")
    print("   💾 Постійні томи для даних")
    print("   🔄 Автоматичні backup")

    print("\n🚀 Запуск Docker Control Panel...")
    print("🌐 Доступний на: http://localhost:8080")
    print("🐳 Docker команди:")
    print("   docker logs telegram_monitor_control  # Переглянути логи")
    print("   docker restart telegram_monitor_control  # Перезапустити")
    print("=" * 60)

    uvicorn.run(app, host="0.0.0.0", port=8080)