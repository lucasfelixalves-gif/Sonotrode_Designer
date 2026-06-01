@echo off
:: Dynamically navigate to the folder where this .bat file lives
cd /d "%~dp0"

:: Wake up the environment (You will need to update this path for the new PC!)
call "C:\Users\lucas\miniforge3\Scripts\activate.bat" sonotrode_lab

:: Launch the application
start pythonw scripts/main.py

exit