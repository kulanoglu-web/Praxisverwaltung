@echo off
setlocal
cd /d "%~dp0"
if not exist .venv py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
pyinstaller --noconfirm --clean PraxisPro.spec
if errorlevel 1 exit /b %errorlevel%
echo Build fertig: dist\PraxisPro.exe
endlocal
