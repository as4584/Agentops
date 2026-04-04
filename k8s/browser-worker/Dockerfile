FROM backend-app:latest

# System deps: Xvfb (virtual display), x11vnc (VNC server),
# websockify+novnc (web viewer), and Chromium runtime libs.
# Debian Trixie-based image (from backend-app).
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    x11vnc \
    websockify \
    novnc \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libxkbcommon0 \
    libasound2 \
    libpangocairo-1.0-0 \
    libcups2 \
    fonts-liberation \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./requirements-browser.txt
RUN pip install --no-cache-dir -r requirements-browser.txt

# Install Playwright's bundled Chromium (runtime libs installed above)
RUN playwright install chromium

COPY entrypoint.sh server.py ./
RUN chmod +x entrypoint.sh

# 8080 = FastAPI (Agentop calls this)
# 6080 = noVNC web viewer (you watch here)
EXPOSE 8080 6080

ENTRYPOINT ["./entrypoint.sh"]
