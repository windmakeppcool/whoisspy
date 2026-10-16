// preload：把 sidecar 连接信息（port/token）暴露给 renderer（pc-game 二）
// token 只在启动参数里传递，不落盘/不进渲染层以外的全局
'use strict'

const { contextBridge } = require('electron')

function argValue(name) {
  const prefix = `--${name}=`
  const found = process.argv.find((a) => a.startsWith(prefix))
  return found ? found.slice(prefix.length) : ''
}

contextBridge.exposeInMainWorld('whoisspy', {
  port: Number(argValue('ws-port')) || 0,
  token: argValue('ws-token'),
})