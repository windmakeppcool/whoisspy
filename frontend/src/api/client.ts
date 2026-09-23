// REST client（对齐 docs/api.md）
import type { BoardPreset, MatchInfo, Persona, UsageSummary, GameEvent } from '../model/types'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000'

async function j<T>(resp: Response): Promise<T> {
  if (!resp.ok) throw new Error(`${resp.status} ${await resp.text()}`)
  return resp.json() as Promise<T>
}

async function get<T>(path: string): Promise<T> {
  return j<T>(await fetch(`${BASE}${path}`))
}

export const api = {
  async createMatch(body: {
    game_type: string
    board: { id: string }
    seats: Array<{ seat: number; persona_id: string; model: string; base_url?: string; api_key_env?: string }>
  }): Promise<MatchInfo> {
    const resp = await fetch(`${BASE}/api/matches`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    return j<MatchInfo>(resp)
  },
  listMatches(): Promise<MatchInfo[]> {
    return get('/api/matches')
  },
  getMatch(id: number | string): Promise<MatchInfo> {
    return get(`/api/matches/${id}`)
  },
  events(id: number | string, afterSeq: number, view: string): Promise<GameEvent[]> {
    return get(`/api/matches/${id}/events?after_seq=${afterSeq}&view=${view}`)
  },
  usage(id: number | string): Promise<UsageSummary> {
    return get(`/api/matches/${id}/usage`)
  },
  async exportDialog(id: number | string): Promise<void> {
    const resp = await fetch(`${BASE}/api/matches/${id}/export`)
    if (!resp.ok) throw new Error(`导出失败: ${resp.status}`)
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `match-${id}-dialog.json`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  },
  async stop(id: number | string): Promise<{ ok: boolean }> {
    const resp = await fetch(`${BASE}/api/matches/${id}/stop`, { method: 'POST' })
    return j(resp)
  },
  boards(): Promise<BoardPreset[]> {
    return get('/api/catalog/boards')
  },
  personas(): Promise<Persona[]> {
    return get('/api/catalog/personas')
  },
}
