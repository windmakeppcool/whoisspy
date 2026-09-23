// 对局模型类型（设计稿阶段与 docs/events-storage.md 对齐的简化版）
export type Team = 'wolf' | 'good'
export type RoleId = 'wolf' | 'wolf_king' | 'seer' | 'witch' | 'hunter' | 'guard' | 'villager'
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

export interface FeedItem {
  kind: 'speech' | 'channel' | 'last_words' | 'system'
  seat?: number
  text: string
  monologue?: string
}

export interface VoteRound {
  day: number
  title: string
  tally: Record<number, number> // 座位号 -> 票数
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

export const ROLE_NAMES: Record<RoleId, string> = {
  wolf: '狼人',
  wolf_king: '狼王',
  seer: '预言家',
  witch: '女巫',
  hunter: '猎人',
  guard: '守卫',
  villager: '平民',
}
