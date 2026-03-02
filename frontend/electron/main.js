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

// ─── Wait for a URL to become available ──────────────────────────────────────
function waitForPort(url, maxMs = 30000) {
  return new Promise((resolve) => {
    const start = Date.now()
    const check = () => {
      http.get(url, (res) => {
        if (res.statusCode < 500) resolve()
        else retry()
      }).on('error', retry)
    }
    const retry = () => {
      if (Date.now() - start > maxMs) { resolve(); return }
      setTimeout(check, 500)
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
    backgroundColor: '#0a0a0a',
    show: false,
    autoHideMenuBar: true,
  })

  mainWindow.removeMenu()

  // Wait for Next.js to be ready before loading
  await waitForPort('http://localhost:3007', 45000)
  mainWindow.loadURL('http://localhost:3007')

  mainWindow.once('ready-to-show', () => {
    mainWindow.show()
    mainWindow.focus()
    // Force a repaint to fix black-screen on Linux compositors
    mainWindow.webContents.invalidate()
  })

  mainWindow.webContents.on('did-finish-load', () => {
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
