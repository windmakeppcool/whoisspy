// 事件与对局模型（与后端 docs/events-storage.md 对齐）
export type VisLevel = 'public' | 'seat' | 'god'

export interface GameEvent {
  seq: number
  type: string
  day_index: number
  phase: string
  payload: Record<string, unknown>
}

export interface SeatInfo {
  seat: number
  name: string
  persona_id: string
  base_url: string
  api_key_env: string
  model: string
  role: string
}

export interface MatchInfo {
  id: number
  game_type: string
  ruleset: string
  board: { id?: string; roles?: Record<string, number> }
  rng_seed: number
  status: 'created' | 'running' | 'finished' | 'stopped'
  result: { winner: string; reason: string } | null
  current_seq: number
  created_at: string
  seats: SeatInfo[]
}

export interface BoardPreset {
  id: string
  game_type: string
  ruleset: string
  roles: Record<string, number>
  wolf_meeting_rounds: number
  max_days: number
}

export interface Persona {
  id: string
  name: string
  style: string
  strategy: string
}

export interface UsageSummary {
  total_calls: number
  prompt_tokens: number
  completion_tokens: number
  cost_micros: number
  by_model: Record<string, { calls: number; prompt_tokens: number; completion_tokens: number; cost_micros: number }>
}

export const ROLE_NAMES: Record<string, string> = {
  wolf: '狼人', wolf_king: '狼王', seer: '预言家', witch: '女巫',
  hunter: '猎人', guard: '守卫', villager: '平民',
}

export const ROLE_EMOJI: Record<string, string> = {
  wolf: '🐺', wolf_king: '👑', seer: '🔮', witch: '🧪',
  hunter: '🏹', guard: '🛡️', villager: '🙂',
}

// ---- 设计稿组件沿用类型（SeatCard/SeatColumn/DialogueTheater 等） ----

export type Team = 'wolf' | 'good'
export type Phase = 'night' | 'day'

export interface Seat {
  id: number
  name: string
  persona: string
  model: string
  emoji: string
  role: RoleId
  team: Team
  alive: boolean
  side: 'L' | 'R'
}

export type RoleId = 'wolf' | 'wolf_king' | 'seer' | 'witch' | 'hunter' | 'guard' | 'villager'

export interface FeedItem {
  kind: 'speech' | 'channel' | 'last_words' | 'system'
  seat?: number
  text: string
  monologue?: string
}

export interface VoteRound {
  day: number
  title: string
  tally: Record<number, number>
  exile?: number
}

export interface DemoState {
  phase: Phase
  day: number
  label: string
  feed: FeedItem[]
  sheriff: number | null
  vote: VoteRound | null
  deadSeats: number[]
}

// 设计稿 mock 数据类型
export interface Chapter {
  label: string
  apply(s: DemoState): void
}

export interface MatchMock {
  id: string
  mode: string
  name: string
  seats: Seat[]
  chapters: Chapter[]
  build(chapterIndex: number): DemoState
}
