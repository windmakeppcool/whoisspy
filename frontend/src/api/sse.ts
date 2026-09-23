// SSE 消费：EventSource + Last-Event-ID 重连 + seq 去重 + gap 补拉（docs/frontend.md）
import { api } from './client'
import type { GameEvent } from '../model/types'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000'

export interface SseHandle {
  close(): void
}

export function connectStream(
  matchId: number | string,
  view: 'immersive' | 'god',
  onEvent: (ev: GameEvent) => void,
  onFinish: () => void,
): SseHandle {
  let lastSeq = 0
  let closed = false
  let es: EventSource | null = null
  let reconnectTimer: number | undefined

  // gap 补拉：SSE 缺口用 REST 回填
  async function backfill(fromSeq: number, uptoSeq: number) {
    try {
      const events = await api.events(matchId, fromSeq, view)
      for (const ev of events) {
        if (ev.seq > uptoSeq) break
        onEvent(ev)
        lastSeq = Math.max(lastSeq, ev.seq)
      }
    } catch {
      /* 补拉失败靠下一次重连兜底 */
    }
  }

  function connect() {
    if (closed) return
    const url = `${BASE}/api/matches/${matchId}/stream?view=${view}&last_event_id=${lastSeq}`
    es = new EventSource(url)
    es.addEventListener('game_event', (e) => {
      const ev = JSON.parse((e as MessageEvent).data) as GameEvent
      if (ev.seq <= lastSeq) return // 去重
      if (ev.seq > lastSeq + 1 && lastSeq > 0) {
        void backfill(lastSeq, ev.seq) // gap 补拉（异步，不阻塞当前帧）
      }
      lastSeq = ev.seq
      onEvent(ev)
    })
    es.addEventListener('match_finished', () => {
      onFinish()
      close()
    })
    es.onerror = () => {
      es?.close()
      if (!closed) {
        reconnectTimer = window.setTimeout(connect, 1500)
      }
    }
  }

  function close() {
    closed = true
    if (reconnectTimer) clearTimeout(reconnectTimer)
    es?.close()
  }

  connect()
  return { close }
}
