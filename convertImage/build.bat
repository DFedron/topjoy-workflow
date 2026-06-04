@echo off
setlocal

cd /d "%~dp0"

python -m PyInstaller -F -w convertImageSide.py --icon app.ico --add-data "app.png;."

pause
