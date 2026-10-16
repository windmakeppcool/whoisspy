// Electron 主进程（pc-game 二/五）：窗口生命周期 + sidecar spawn/监督。
// main 层保持「薄」：不解释对局语义（P5）；token/端口注入 renderer（preload）。
'use strict'

const { app, BrowserWindow } = require('electron')
const { spawn } = require('child_process')
const crypto = require('crypto')
const fs = require('fs')
const path = require('path')
const readline = require('readline')

const BACKEND_DIR = path.join(__dirname, '..', 'backend')
const DIST_DIR = path.join(__dirname, '..', 'frontend', 'dist')

let sidecar = null
let mainWindow = null

/** 本地数据集中单一目录（pc-game 六：db + exports + settings，云存档同步点）。 */
function dataDir() {
  return path.join(app.getPath('userData'), 'whoisspy')
}

/** sidecar 启动命令：打包后走 PyInstaller 单目录产物；开发走 python -m app.main。 */
function sidecarLaunch(token, dbPath, baseDir) {
  const bundled = path.join(process.resourcesPath, 'whoisspy-engine', 'whoisspy-engine.exe')
  if (app.isPackaged && fs.existsSync(bundled)) {
    return {
      cmd: bundled,
      args: ['--serve', '--token', token, '--db', dbPath, '--base-dir', baseDir],
      cwd: path.dirname(bundled),
    }
  }
  return {
    cmd: 'python',
    args: ['-m', 'app.main', '--serve', '--token', token,
           '--db', dbPath, '--base-dir', baseDir],
    cwd: BACKEND_DIR,
  }
}

/** 启动 sidecar；stdout 首行 = 实际端口（15-serve 一）。返回 {port, token}。 */
function startSidecar() {
  const token = crypto.randomBytes(16).toString('hex')
  const base = dataDir()
  fs.mkdirSync(base, { recursive: true })
  const db = path.join(base, 'whoisspy.db')
  const { cmd, args, cwd } = sidecarLaunch(token, db, base)
  sidecar = spawn(cmd, args, { cwd, env: { ...process.env } })
  sidecar.on('exit', (code) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('sidecar-exit', code)
    }
  })
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('sidecar 启动超时（15s）')), 15000)
    sidecar.once('error', (e) => {
      clearTimeout(timer)
      reject(new Error(`sidecar 启动失败：${e.message}`))
    })
    const rl = readline.createInterface({ input: sidecar.stdout })
    rl.once('line', (line) => {
      const port = parseInt(String(line).trim(), 10)
      if (Number.isInteger(port) && port > 0) {
        clearTimeout(timer)
        resolve({ port, token })
      }
    })
  })
}

function createWindow(port, token) {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    title: 'whoisspy',
    backgroundColor: '#2d2a3e',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      additionalArguments: [`--ws-port=${port}`, `--ws-token=${token}`],
    },
  })
  // 开发：VITE_DEV_SERVER_URL（如 http://localhost:5173）；生产：frontend 构建产物
  if (process.env.VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL)
  } else {
    mainWindow.loadFile(path.join(DIST_DIR, 'index.html'))
  }
  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

app.whenReady().then(async () => {
  try {
    const { port, token } = await startSidecar()
    createWindow(port, token)
  } catch (e) {
    // sidecar 不可用：仍开窗口（纯复盘模式），renderer 会提示未连接引擎
    console.error('sidecar 启动失败：', e.message)
    createWindow(0, '')
  }
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  // 崩溃隔离：窗口关闭即停 sidecar（对局事件已落库，可回放）
  if (sidecar) {
    sidecar.kill()
    sidecar = null
  }
})