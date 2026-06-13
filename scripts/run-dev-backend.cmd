@echo off
set PYTHONPATH=src
.venv-win\Scripts\python.exe -m uvicorn email_assistant_app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir src
