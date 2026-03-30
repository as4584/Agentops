@echo off
title Agentop - Local AI Control Center
echo.
echo  ========================================
echo    Agentop - Starting...
echo  ========================================
echo.
echo  Starting backend, frontend, and native window.
echo  This may take 15-30 seconds on first launch.
echo  DO NOT close this window — it keeps services running.
echo.
wsl -d Ubuntu -u root -- bash -lc "cd /root/studio/testing/Agentop && source .venv/bin/activate && python3 app.py"
echo.
echo  Agentop stopped. You can close this window.
pause
