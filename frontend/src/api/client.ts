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
