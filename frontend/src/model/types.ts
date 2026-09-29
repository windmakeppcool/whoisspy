// 设计稿组件沿用类型（SeatCard/SeatColumn/DialogueTheater 等）与展示辅助
// 展示文档（导出 JSON v2）类型在 ./display（schema 权威：docs/backend/11-export.md 第五节）

export type Team = 'wolf' | 'good'
export type Phase = 'night' | 'day'

export const ROLE_NAMES: Record<string, string> = {
  wolf: '狼人', wolf_king: '狼王', seer: '预言家', witch: '女巫',
  hunter: '猎人', guard: '守卫', villager: '平民',
}

export const ROLE_EMOJI: Record<string, string> = {
  wolf: '🐺', wolf_king: '👑', seer: '🔮', witch: '🧪',
  hunter: '🏹', guard: '🛡️', villager: '🙂',
}

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

// 板子展示标签：standard-12/9 显示全名，其余按人数（roles/seats 求和）
export function boardLabel(ruleset: string, counts?: Record<string, number> | null): string {
  if (ruleset === 'standard-12') return '标准 12 人局'
  if (ruleset === 'standard-9') return '标准 9 人局'
  const n = counts ? Object.values(counts).reduce((a, b) => a + b, 0) : 0
  return n ? `${n} 人局` : '极简局'
}
