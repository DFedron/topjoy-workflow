@echo off
setlocal

if not exist .venv (
    py -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

pyinstaller --noconfirm --clean --onefile --windowed --name TopjoyDecryptTool decrypt_gui.py

echo.
echo Build done. EXE path: dist\TopjoyDecryptTool.exe
pause
