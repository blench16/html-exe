@echo off
cd /d "%~dp0"
echo ===== HTML2EXE build =====
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo [1/4] Creating clean build environment...
if not exist .venv_build python -m venv .venv_build
if errorlevel 1 goto fail
call .venv_build\Scripts\activate.bat
echo [2/4] Installing dependencies...
python -m pip install pyinstaller pywebview
if errorlevel 1 goto fail
echo [3/4] Building stub.exe ...
python -m PyInstaller --noconsole --onefile --clean --collect-all webview --exclude-module tkinter --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2 --exclude-module PySide6 --exclude-module qtpy --exclude-module numpy --exclude-module pandas --exclude-module matplotlib --exclude-module scipy --exclude-module PIL --exclude-module IPython --name stub stub.py
if not exist dist\stub.exe goto fail
for %%F in (dist\stub.exe) do echo stub.exe size: %%~zF bytes
echo [4/4] Building HTML2EXE.exe ...
python -m PyInstaller --noconsole --onefile --name HTML2EXE --add-data "dist\stub.exe;." builder.py
if not exist dist\HTML2EXE.exe goto fail
echo.
echo DONE. Your tool is: dist\HTML2EXE.exe
pause
goto :eof
:fail
echo.
echo BUILD FAILED. Please copy the error text above and send it to me.
pause
