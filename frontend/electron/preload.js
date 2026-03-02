/**
 * Agentop Electron Preload Script
 * Safely exposes minimal context to the renderer.
 */

const { contextBridge } = require('electron')

contextBridge.exposeInMainWorld('agentop', {
  version: process.env.npm_package_version || '1.0.0',
  platform: process.platform,
  isElectron: true,
})
