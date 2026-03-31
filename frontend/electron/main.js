/**
 * Agentop Electron Main Process
 * Wraps the Next.js dashboard in a native app window with tray icon.
 */

const { app, BrowserWindow, Tray, Menu, shell, nativeImage } = require('electron')
const path = require('path')
const { spawn } = require('child_process')
const http = require('http')

// Required for running as root on Linux without GPU compositor
app.disableHardwareAcceleration()
app.commandLine.appendSwitch('no-sandbox')
app.commandLine.appendSwitch('disable-setuid-sandbox')
app.commandLine.appendSwitch('disable-dev-shm-usage')

let mainWindow
let tray
let backendProcess

const isDev = !app.isPackaged

// ─── Icon paths ──────────────────────────────────────────────────────────────
const ICON_ICO = path.join(__dirname, 'icon.ico')
const ICON_PNG = path.join(__dirname, 'icon.png')
const ICON_PATH = process.platform === 'win32' ? ICON_ICO : ICON_PNG

// ─── Resolve dashboard port (env > port file > default 3007) ─────────────────
const fs = require('fs')
function getDashboardPort() {
  // 1. AGENTOP_DASHBOARD_PORT env var (set by app.py when it spawns Electron)
  if (process.env.AGENTOP_DASHBOARD_PORT) {
    return parseInt(process.env.AGENTOP_DASHBOARD_PORT, 10)
  }
  // 2. Port file written by app.py
  const portFile = path.join(__dirname, '..', '..', '.dashboard_port')
  try {
    const port = parseInt(fs.readFileSync(portFile, 'utf-8').trim(), 10)
    if (port > 0 && port < 65536) return port
  } catch { /* file doesn't exist, fall through */ }
  // 3. Default
  return 3007
}
const DASHBOARD_PORT = getDashboardPort()
const DASHBOARD_URL = `http://localhost:${DASHBOARD_PORT}`

// ─── Wait for a URL to return HTTP 200 ───────────────────────────────────────
function waitForPort(url, maxMs = 60000) {
  return new Promise((resolve, reject) => {
    const start = Date.now()
    const check = () => {
      http.get(url, (res) => {
        // Only accept 200 — not 404 or other codes
        if (res.statusCode === 200) {
          res.resume()
          resolve()
        } else {
          res.resume()
          retry()
        }
      }).on('error', retry)
    }
    const retry = () => {
      if (Date.now() - start > maxMs) {
        reject(new Error(`Timed out waiting for ${url} after ${maxMs}ms`))
        return
      }
      setTimeout(check, 800)
    }
    check()
  })
}

// ─── Create main window ───────────────────────────────────────────────────────
async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 600,
    title: 'Agentop',
    icon: ICON_PATH,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    },
    backgroundColor: '#141417',
    show: false,
    autoHideMenuBar: true,
  })

  mainWindow.removeMenu()

  // Wait for Next.js to be ready before loading
  try {
    await waitForPort(DASHBOARD_URL, 60000)
  } catch (err) {
    console.error('Frontend not ready:', err.message)
  }
  mainWindow.loadURL(DASHBOARD_URL)

  mainWindow.once('ready-to-show', () => {
    mainWindow.show()
    mainWindow.focus()
    mainWindow.webContents.invalidate()
  })

  // Auto-retry on load failure (404, connection refused, etc.)
  mainWindow.webContents.on('did-fail-load', (_ev, code, desc) => {
    console.error(`Page load failed (${code}): ${desc}. Retrying in 3s...`)
    setTimeout(() => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.loadURL(DASHBOARD_URL)
      }
    }, 3000)
  })

  mainWindow.webContents.on('did-finish-load', () => {
    // Check if we got a real page or an error page
    mainWindow.webContents.executeJavaScript(
      `document.title.includes('404') || document.body.innerText.includes('404')`
    ).then(is404 => {
      if (is404) {
        console.log('Got 404 page, retrying in 3s...')
        setTimeout(() => {
          if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.loadURL(DASHBOARD_URL)
          }
        }, 3000)
      }
    }).catch(() => {})
    mainWindow.webContents.invalidate()
  })

  // Minimise to tray on close instead of quitting
  mainWindow.on('close', (e) => {
    if (!app.isQuitting) {
      e.preventDefault()
      mainWindow.hide()
      if (tray) {
        tray.displayBalloon({
          iconType: 'info',
          title: 'Agentop',
          content: 'Still running in the background. Right-click the tray icon to quit.'
        })
      }
    }
  })

  mainWindow.on('closed', () => { mainWindow = null })
}

// ─── System tray ─────────────────────────────────────────────────────────────
function createTray() {
  const icon = nativeImage.createFromPath(ICON_PATH).resize({ width: 16, height: 16 })
  tray = new Tray(icon)

  const menu = Menu.buildFromTemplate([
    {
      label: 'Open Agentop',
      click: () => {
        if (mainWindow) { mainWindow.show(); mainWindow.focus() }
        else createWindow()
      }
    },
    {
      label: 'Open in Browser',
      click: () => shell.openExternal('http://localhost:3007')
    },
    { type: 'separator' },
    {
      label: 'Backend Health',
      click: () => shell.openExternal('http://localhost:8000/health')
    },
    {
      label: 'API Docs',
      click: () => shell.openExternal('http://localhost:8000/docs')
    },
    { type: 'separator' },
    {
      label: 'Quit Agentop',
      click: () => {
        app.isQuitting = true
        app.quit()
      }
    }
  ])

  tray.setToolTip('Agentop — Multi-Agent Dashboard')
  tray.setContextMenu(menu)

  tray.on('double-click', () => {
    if (mainWindow) { mainWindow.show(); mainWindow.focus() }
    else createWindow()
  })
}

// ─── App lifecycle ────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  createTray()
  await createWindow()

  app.on('activate', () => {
    if (!mainWindow) createWindow()
  })
})

app.on('window-all-closed', () => {
  // Don't quit on macOS or when we have a tray
  if (process.platform !== 'darwin' && !tray) app.quit()
})

app.on('before-quit', () => {
  app.isQuitting = true
})
