@echo off
echo Starting OmniStock POS & Inventory Django Server...
cd /d "%~dp0"
call venv\Scripts\activate.bat
echo Opening browser...
start http://127.0.0.1:8000/
python manage.py runserver 0.0.0.0:8000
pause
