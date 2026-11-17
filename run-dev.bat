@echo off
rem Runs Blue Cench Chat from source.
rem   run-dev.bat            normal run
rem   run-dev.bat bob        DEVELOPMENT TEST MODE: second isolated profile on the same PC.
rem                          Both instances talk over real local sockets (no simulation).
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (python -m venv .venv && .venv\Scripts\python -m pip install -r requirements-dev.txt)
if "%~1"=="" (
  .venv\Scripts\python main.py
) else (
  .venv\Scripts\python main.py --profile %~1
)
