@echo off
setlocal
cd /d "%~dp0"
call build_windows.bat
if errorlevel 1 exit /b %errorlevel%
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
 echo Inno Setup 6 wurde nicht gefunden.
 exit /b 1
)
"%ISCC%" installer\PraxisPro.iss
if errorlevel 1 exit /b %errorlevel%
echo Setup fertig im Ordner setup.
endlocal
