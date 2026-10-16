// ApiSource：WS 直播帧源（docs/backend/15-serve.md，frontend.md 八「阶段 B 预留」转正）
// 档 1 观战闭环：connect → createMatch → 帧流 append 进展示文档模型；
// list/sync（复盘）复用同一连接；断线自动重连，重连后客户端自行 sync 取全量。
import type { DisplayDoc, MatchSummary, View } from '../model/display'
import type { LiveFrame } from '../model/live'
import type { MatchSource } from './MatchSource'

export interface ApiOptions {
  /** ws://127.0.0.1:<port>（Electron main 注入或 VITE_WS_URL） */
  url: string
  /** 握手 token（Electron main 注入或 VITE_WS_TOKEN） */
  token: string
  /** 断线重连间隔 ms（缺省 800） */
  reconnectMs?: number
  /** 请求应答超时 ms（缺省 8000） */
  timeoutMs?: number
}

export type PaceOp = 'pause' | 'resume' | 'frame' | 'speed'

const FRAME_TYPES = new Set([
  'match_open', 'segment_open', 'line', 'segment_close',
  'seat_role', 'usage', 'finished', 'stopped',
])

interface Pending {
  resolve: (v: unknown) => void
  reject: (e: Error) => void
  timer: ReturnType<typeof setTimeout>
}

export class ApiSource implements MatchSource {
  private ws: WebSocket | null = null
  private readonly url: string
  private readonly token: string
  private readonly reconnectMs: number
  private readonly timeoutMs: number
  private pending: Pending[] = [] // 请求应答 FIFO（应答与帧流同连接混流）
  private readonly frameHandlers = new Set<(f: LiveFrame) => void>()
  private ready: Promise<void> | null = null
  private closed = false
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null

  constructor(opts: ApiOptions) {
    this.url = opts.url
    this.token = opts.token
    this.reconnectMs = opts.reconnectMs ?? 800
    this.timeoutMs = opts.timeoutMs ?? 8000
  }

  // ---------- 连接 ----------

  /** 建立连接并完成握手（幂等）；失败抛错，由调用方展示。 */
  connect(): Promise<void> {
    if (!this.ready) this.ready = this.open()
    return this.ready
  }

  private open(): Promise<void> {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this.url)
      ws.onopen = () => {
        this.hello(ws).then(() => resolve(), (e) => reject(e))
      }
      ws.onmessage = (ev) => this.onMessage(ev.data)
      ws.onclose = () => {
        this.ws = null
        this.ready = null
        this.failPending(new Error('连接断开'))
        if (!this.closed) {
          this.reconnectTimer = setTimeout(() => void this.connect(), this.reconnectMs)
        }
        reject(new Error('连接关闭'))
      }
      ws.onerror = () => ws.close()
      this.ws = ws
    })
  }

  private hello(ws: WebSocket): Promise<void> {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        cleanup()
        reject(new Error('握手超时'))
      }, this.timeoutMs)
      const onMsg = (ev: MessageEvent) => {
        let m: Record<string, unknown>
        try {
          m = JSON.parse(String(ev.data))
        } catch {
          return
        }
        if (m.type === 'ok') {
          cleanup()
          resolve()
        } else if (m.type === 'error') {
          cleanup()
          reject(new Error(String(m.message ?? '握手失败')))
        }
      }
      const cleanup = () => {
        clearTimeout(timer)
        ws.removeEventListener('message', onMsg)
      }
      ws.addEventListener('message', onMsg)
      ws.send(JSON.stringify({ type: 'hello', token: this.token }))
    })
  }

  /** 主动关闭（应用退出）；不再重连。 */
  close(): void {
    this.closed = true
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.ws?.close()
  }

  private failPending(e: Error): void {
    for (const p of this.pending) {
      clearTimeout(p.timer)
      p.reject(e)
    }
    this.pending = []
  }

  // ---------- 消息 ----------

  private onMessage(raw: unknown): void {
    let m: LiveFrame
    try {
      m = JSON.parse(String(raw)) as LiveFrame
    } catch {
      return
    }
    if (m.type === 'ok' || m.type === 'error' || m.type === 'snapshot') {
      const p = this.pending.shift()
      if (!p) return // hello 的 ok（hello 用独立监听）
      clearTimeout(p.timer)
      if (m.type === 'error') p.reject(new Error(String(m.message ?? '请求失败')))
      else p.resolve(m)
      return
    }
    if (FRAME_TYPES.has(m.type)) {
      for (const cb of this.frameHandlers) cb(m)
    }
    // 未知类型静默忽略（协议向前兼容）
  }

  private send(type: string, payload?: Record<string, unknown>): Promise<unknown> {
    return new Promise((resolve, reject) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        reject(new Error('连接未就绪'))
        return
      }
      const timer = setTimeout(() => {
        const i = this.pending.indexOf(item)
        if (i >= 0) this.pending.splice(i, 1)
        reject(new Error('请求超时'))
      }, this.timeoutMs)
      const item: Pending = { resolve, reject, timer }
      this.pending.push(item)
      this.ws.send(JSON.stringify({ type, ...payload }))
    })
  }

  // ---------- MatchSource（复盘接口） ----------

  async list(): Promise<MatchSummary[]> {
    await this.connect()
    const resp = (await this.send('list')) as { matches?: MatchSummary[] }
    return resp.matches ?? []
  }

  /** serve 直播源仅提供 god 视角（sync 当前前缀快照）。 */
  async load(_matchId: number, view: View): Promise<DisplayDoc> {
    if (view !== 'god') throw new Error('serve 直播源仅提供 god 视角')
    await this.connect()
    const resp = (await this.send('sync')) as { doc: DisplayDoc }
    return resp.doc
  }

  // ---------- 直播 ----------

  /** 建局（观战 = 全 LLM 座位）；返回 match_id；帧流经 onFrame 派发。 */
  async createMatch(opts: { seed?: number; paused?: boolean } = {}): Promise<number> {
    await this.connect()
    const resp = (await this.send('create', {
      game: 'werewolf',
      board: {},
      seed: opts.seed,
      paused: opts.paused,
      seats: Array.from({ length: 9 }, (_, i) => ({ seat: i + 1, type: 'llm' })),
    })) as { match_id?: number }
    if (resp.match_id == null) throw new Error('建局应答缺少 match_id')
    return Number(resp.match_id)
  }

  /** 节奏控制（15-serve 三）。 */
  async pace(op: PaceOp, value?: number): Promise<void> {
    await this.connect()
    await this.send('pace', { op, ...(value !== undefined ? { value } : {}) })
  }

  /** 全量快照（断线恢复/窗口重开）。 */
  async sync(): Promise<DisplayDoc> {
    await this.connect()
    const resp = (await this.send('sync')) as { doc: DisplayDoc }
    return resp.doc
  }

  onFrame(cb: (f: LiveFrame) => void): void {
    this.frameHandlers.add(cb)
  }

  offFrame(cb: (f: LiveFrame) => void): void {
    this.frameHandlers.delete(cb)
  }
}

/** 应用环境里的 sidecar 连接信息（Electron preload 注入；浏览器 dev 走 VITE_WS_URL）。 */
export interface ApiBootstrap {
  port?: number
  token?: string
}

export function apiOptionsFromEnv(
  bootstrap: ApiBootstrap | undefined,
  env: Record<string, string | undefined>,
): ApiOptions | null {
  const url = bootstrap?.port
    ? `ws://127.0.0.1:${bootstrap.port}`
    : env.VITE_WS_URL
  const token = bootstrap?.token ?? env.VITE_WS_TOKEN
  if (!url || !token) return null
  return { url, token }
}