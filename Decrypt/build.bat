@echo off
setlocal

if not exist .venv (
    py -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pillow

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist TopjoyDecryptTool.spec del /f /q TopjoyDecryptTool.spec

if exist app.png (
    python -c "from PIL import Image; Image.open('app.png').save('app.ico', format='ICO')"
)

pyinstaller --noconfirm --clean --onefile --windowed --name DecryptTool decrypt_gui.py --icon app.ico --add-data "app.png;."

echo.
echo Build done. EXE path: dist\TopjoyDecryptTool.exe
pause
