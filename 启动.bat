@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%PYTHON%" goto run
set "PYTHON="
for /f "delims=" %%P in ('where python.exe 2^>nul') do if not defined PYTHON set "PYTHON=%%P"
if defined PYTHON goto run
echo Python was not found. Install Python 3.10+ with tkinter, then try again.
pause
exit /b 1
:run
if not "%~1"=="" goto console
for %%P in ("%PYTHON%") do set "PYTHONW=%%~dpPpythonw.exe"
if not exist "%PYTHONW%" goto console
start "" "%PYTHONW%" -B "%~dp0my_devices.py"
exit /b 0
:console
"%PYTHON%" -B "%~dp0my_devices.py" %*
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" pause
exit /b %APP_EXIT%
