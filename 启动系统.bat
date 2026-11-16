@echo off
chcp 65001 >nul
cd /d %~dp0
python -c "import django,pymysql,pandas" >nul 2>&1
if errorlevel 1 python -m pip install -r requirements.txt
python manage.py migrate
python manage.py init_demo_data
python manage.py runserver 0.0.0.0:8020
pause
