@echo off
:: Dynamically navigate to the folder where this .bat file lives
cd /d "%~dp0"

:: Run the pythonw.exe directly from your specific environment folder
"C:\MiniForge3\envs\sonotrode_lab\pythonw.exe" scripts\main.py

exit