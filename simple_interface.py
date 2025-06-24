from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import json
import os
from datetime import datetime
from typing import List, Dict, Optional, Any

app = FastAPI(title="Telegram Monitor Config")


# Читаємо HTML файл
def get_html_content():
    try:
        with open("config_editor.html", "r", encoding="utf-8") as f:
            html_content = f.read()

        # Вставляємо поточні дані користувача
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        html_content = html_content.replace(
            '<span class="badge bg-secondary">2025-06-02 14:07:23 UTC</span>',
            f'<span class="badge bg-secondary">{current_time}</span>',
        )
        return html_content
    except FileNotFoundError:
        return """
        <html><body>
        <h1>❌ Помилка</h1>
        <p>Файл config_editor.html не знайдено!</p>
        <p>Переконайтеся що файл знаходиться в тій же папці що і веб-сервер.</p>
        </body></html>
        """


@app.get("/", response_class=HTMLResponse)
async def get_config_page():
    """Головна сторінка з інтерфейсом"""
    return HTMLResponse(content=get_html_content())


@app.get("/api/config")
async def get_config():
    """Читає ваш існуючий config.json"""
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

        print(f"✅ Конфігурацію завантажено: {len(config.get('groups', []))} груп")
        return config

    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Помилка парсингу JSON: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Помилка читання файлу: {str(e)}")


@app.post("/api/config")
async def save_config(config: Dict[str, Any]):
    """Зберігає конфігурацію у ваш config.json"""
    try:
        # Створюємо backup
        if os.path.exists("config.json"):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"config_backup_{timestamp}.json"
            import shutil

            shutil.copy("config.json", backup_name)
            print(f"📁 Створено backup: {backup_name}")

        # Зберігаємо нову конфігурацію
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        print(f"💾 Конфігурацію збережено: {len(config.get('groups', []))} груп")
        return {
            "status": "success",
            "message": f"Конфігурацію збережено. Груп: {len(config.get('groups', []))}",
        }

    except Exception as e:
        print(f"❌ Помилка збереження: {e}")
        raise HTTPException(status_code=500, detail=f"Помилка збереження: {str(e)}")


@app.get("/api/backup-list")
async def list_backups():
    """Показує список backup файлів"""
    try:
        backups = [
            f
            for f in os.listdir(".")
            if f.startswith("config_backup_") and f.endswith(".json")
        ]
        backups.sort(reverse=True)  # Новіші спочатку
        return {"backups": backups}
    except Exception as e:
        return {"backups": [], "error": str(e)}


@app.post("/api/restore-backup/{backup_name}")
async def restore_backup(backup_name: str):
    """Відновлює конфігурацію з backup"""
    try:
        if not os.path.exists(backup_name):
            raise HTTPException(status_code=404, detail="Backup файл не знайдено")

        # Створюємо backup поточної конфігурації
        if os.path.exists("config.json"):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            current_backup = f"config_before_restore_{timestamp}.json"
            import shutil

            shutil.copy("config.json", current_backup)

        # Відновлюємо з backup
        import shutil

        shutil.copy(backup_name, "config.json")

        return {
            "status": "success",
            "message": f"Конфігурацію відновлено з {backup_name}",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Помилка відновлення: {str(e)}")


if __name__ == "__main__":
    import uvicorn

    print("🤖 Telegram Monitor - Веб Конфігуратор")
    print("=" * 50)
    print(f"📅 Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"👤 Користувач: SergZels")
    print(f"📁 Робоча директорія: {os.getcwd()}")

    # Перевіряємо наявність файлів
    files_status = {
        "config.json": os.path.exists("config.json"),
        "config_editor.html": os.path.exists("config_editor.html"),
    }

    print("\n📋 Статус файлів:")
    for file, exists in files_status.items():
        status = "✅ Знайдено" if exists else "❌ Відсутній"
        print(f"   {file}: {status}")

    if not files_status["config_editor.html"]:
        print("\n⚠️  УВАГА: Файл config_editor.html не знайдено!")
        print("   Створіть його з коду вище або інтерфейс не працюватиме.")

    if files_status["config.json"]:
        try:
            with open("config.json", "r") as f:
                config = json.load(f)
            groups_count = len(config.get("groups", []))
            print(f"\n📊 Поточна конфігурація: {groups_count} груп")
        except:
            print("\n⚠️  config.json існує але містить помилки")
    else:
        print("\n💡 config.json буде створено після першого збереження")

    print("\n🚀 Запуск веб-сервера...")
    print("🌐 Відкрийте у браузері: http://localhost:8080")
    print("⏹️  Зупинити: Ctrl+C")
    print("=" * 50)

    uvicorn.run(app, host="0.0.0.0", port=8080)

# from fastapi import FastAPI, HTTPException
# from fastapi.responses import HTMLResponse, FileResponse
# from fastapi.staticfiles import StaticFiles
# from pydantic import BaseModel
# import json
# import os
# from datetime import datetime
# from typing import List, Dict, Optional
#
# app = FastAPI(title="Telegram Monitor Config")
#
#
# # Модель для конфігурації
# class TelegramConfig(BaseModel):
#     api_id: int
#     api_hash: str
#     session_string: str
#
#
# class GlobalSettings(BaseModel):
#     check_interval_seconds: int
#     notification_user_id: str
#     timezone: str
#     night_hours: Dict[str, str]
#
#
# class MonitoringConfig(BaseModel):
#     enabled: bool
#     day_inactive_minutes: int
#     night_inactive_minutes: int
#
#
# class ApiRebootConfig(BaseModel):
#     enabled: bool
#     url: Optional[str] = None
#     method: str = "GET"
#     headers: Optional[Dict] = None
#
#
# class GroupConfig(BaseModel):
#     chat_id: int
#     name: str
#     description: str
#     monitoring: MonitoringConfig
#     api_reboot: ApiRebootConfig
#
#
# class FullConfig(BaseModel):
#     telegram: TelegramConfig
#     global_settings: GlobalSettings
#     groups: List[GroupConfig]
#
#
# @app.get("/", response_class=HTMLResponse)
# async def get_config_page():
#     """Повертає HTML сторінку конфігурації"""
#     try:
#         with open("config_editor.html", "r", encoding="utf-8") as f:
#             return HTMLResponse(content=f.read())
#     except FileNotFoundError:
#         return HTMLResponse(
#             content="<h1>Файл config_editor.html не знайдено</h1>", status_code=404
#         )
#
#
# @app.get("/api/config")
# async def get_config():
#     """Отримати поточну конфігурацію"""
#     try:
#         if os.path.exists("config.json"):
#             with open("config.json", "r", encoding="utf-8") as f:
#                 config = json.load(f)
#             return config
#         else:
#             # Повертаємо шаблон конфігурації
#             return {
#                 "telegram": {"api_id": 0, "api_hash": "", "session_string": ""},
#                 "global_settings": {
#                     "check_interval_seconds": 60,
#                     "notification_user_id": "me",
#                     "timezone": "Europe/Kiev",
#                     "night_hours": {"start": "22:00", "end": "08:00"},
#                 },
#                 "groups": [],
#             }
#     except Exception as e:
#         raise HTTPException(
#             status_code=500, detail=f"Помилка читання конфігурації: {str(e)}"
#         )
#
#
# @app.post("/api/config")
# async def save_config(config: FullConfig):
#     """Зберегти конфігурацію"""
#     try:
#         # Створюємо backup
#         if os.path.exists("config.json"):
#             timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
#             backup_name = f"config_backup_{timestamp}.json"
#             import shutil
#
#             shutil.copy("config.json", backup_name)
#
#         # Зберігаємо нову конфігурацію
#         with open("config.json", "w", encoding="utf-8") as f:
#             json.dump(config.dict(), f, ensure_ascii=False, indent=2)
#
#         return {"status": "success", "message": "Конфігурацію збережено успішно"}
#
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Помилка збереження: {str(e)}")
#
#
# @app.post("/api/config/validate")
# async def validate_config(config: FullConfig):
#     """Перевірити валідність конфігурації"""
#     errors = []
#
#     # Перевірка Telegram налаштувань
#     if not config.telegram.api_id:
#         errors.append("API ID не вказано")
#     if not config.telegram.api_hash:
#         errors.append("API Hash не вказано")
#     if not config.telegram.session_string:
#         errors.append("Session string не вказано")
#
#     # Перевірка груп
#     chat_ids = []
#     for i, group in enumerate(config.groups):
#         if group.chat_id in chat_ids:
#             errors.append(f"Дублікат chat_id: {group.chat_id}")
#         chat_ids.append(group.chat_id)
#
#         if not group.name:
#             errors.append(f"Група {i + 1}: назва не вказана")
#
#         if group.api_reboot.enabled and not group.api_reboot.url:
#             errors.append(
#                 f"Група '{group.name}': API reboot увімкнено але URL не вказано"
#             )
#
#     if errors:
#         return {"valid": False, "errors": errors}
#     else:
#         return {"valid": True, "message": "Конфігурація валідна"}
#
#
# if __name__ == "__main__":
#     import uvicorn
#
#     print("🚀 Запуск веб-інтерфейсу конфігурації...")
#     print("📝 Відкрийте http://localhost:8080 у браузері")
#     uvicorn.run(app, host="0.0.0.0", port=8080)