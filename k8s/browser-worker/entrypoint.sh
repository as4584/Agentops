#!/bin/bash
set -e

echo "[browser-worker] Starting Xvfb virtual display on :99..."
Xvfb :99 -screen 0 1280x800x24 &
export DISPLAY=:99
sleep 1

echo "[browser-worker] Starting x11vnc VNC server..."
x11vnc -display :99 -nopw -listen 0.0.0.0 -xkb -forever -shared -bg -o /tmp/x11vnc.log

echo "[browser-worker] Starting noVNC websocket proxy on port 6080..."
websockify --web /usr/share/novnc 6080 localhost:5900 &

echo "[browser-worker] Starting FastAPI on port 8080..."
exec uvicorn server:app --host 0.0.0.0 --port 8080
