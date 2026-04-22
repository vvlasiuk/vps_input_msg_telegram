@echo off
REM Створення та активація venv, встановлення залежностей
python -m venv venv
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
    pip install --upgrade pip
    pip install -r requirements.txt
    echo venv створено та залежності встановлено.
) else (
    echo Не вдалося створити venv.
)
pause
