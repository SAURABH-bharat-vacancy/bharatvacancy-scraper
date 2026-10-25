@echo off
rem Started by the "BharatVacancy local portals" scheduled task (see install_local_task.ps1).
rem Appends everything to local_runner.log next to this file (git-ignored).
cd /d "%~dp0"
echo. >> local_runner.log
"%LOCALAPPDATA%\Programs\Python\Python312\python.exe" local_portals.py >> local_runner.log 2>&1
