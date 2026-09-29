import { fileURLToPath, URL } from 'node:url'
import fs from 'node:fs'
import path from 'node:path'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

// dev：把 ../backend/exports 挂到 /exports（静态导出源，见 docs/frontend.md 第三节；
// 部署时由任意静态服务器把构建产物与 exports/ 同源托管）
const exportsDir = fileURLToPath(new URL('../backend/exports', import.meta.url))

function serveExports(): { name: string; configureServer(server: {
  middlewares: { use: (p: string, h: (req: unknown, res: {
    statusCode: number; setHeader: (k: string, v: string) => void;
    end: (b?: string) => void;
  }) => void) => void }
}): void } {
  return {
    name: 'serve-exports',
    configureServer(server) {
      server.middlewares.use('/exports', (req, res) => {
        const url = (req as { url?: string }).url ?? ''
        const rel = decodeURIComponent(url.split('?')[0]).replace(/^\/+/, '')
        const file = path.resolve(exportsDir, rel)
        if (!file.startsWith(exportsDir + path.sep)) {
          res.statusCode = 403
          res.end('forbidden')
          return
        }
        if (!fs.existsSync(file) || !fs.statSync(file).isFile()) {
          res.statusCode = 404
          res.end('not found')
          return
        }
        res.setHeader('Content-Type', 'application/json; charset=utf-8')
        res.end(fs.readFileSync(file))
      })
    },
  }
}

export default defineConfig({
  plugins: [vue(), serveExports()],
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})