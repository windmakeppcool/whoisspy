// 展示文档（导出 JSON v2）类型与运行时守卫
// schema 唯一权威：docs/backend/11-export.md 第五节（此处仅消费侧镜像）
import { ROLE_NAMES } from './types'

export type View = 'god' | 'public'

export interface DisplayEntry {
  kind: string
  seat: number | null
  text: string
}

export interface DisplayVoteRound {
  title: string
  scope: 'exile' | 'sheriff'
  votes: Record<string, number>
  tally: Record<string, number>
  exiled: number | null
  tie: boolean
}

export interface DisplaySegment {
  label: string
  day_index: number
  is_night: boolean
  entries: DisplayEntry[]
  stage: { alive: number[]; sheriff: number | null }
  votes?: DisplayVoteRound[]
}

export interface DisplaySeat {
  seat: number
  persona_id: string
  persona_name: string
  persona_style: string
  model: string
  role?: string | null
}

export interface DisplayUsage {
  calls: number
  prompt_tokens: number
  completion_tokens: number
  cached_prompt_tokens: number
  cost_micros: number
  cache_hit_rate: number
  fallbacks: number
  rule_errors: number
}

export interface DisplayDoc {
  match_id: number
  exported_at: string
  view: View
  match: {
    seed: number | null
    status: string
    winner: string | null
    reason: string | null
    board: {
      roles?: Record<string, number>
      wolf_meeting_rounds?: number
      max_days?: number
    }
    seats: DisplaySeat[]
    model_assignments?: Array<Record<string, unknown>>
  }
  segments: DisplaySegment[]
  usage: DisplayUsage
}

// 对局索引条目（exports/index.json，列表页数据源）
export interface MatchSummary {
  match_id: number
  seed: number | null
  status: string
  winner: string | null
  reason: string | null
  player_count: number
  exported_at: string
  views: View[]
}

// 座位表情（纯视觉身份，按座位号循环）
export const SEAT_EMOJI = ['🦊', '🦉', '🐻', '🐱', '🦁', '🐰', '🐢', '🐮', '🐙', '🐧', '🦔', '🐝']

export function roleName(role: string | null | undefined): string {
  return (role && ROLE_NAMES[role]) || '？？？'
}

export function roleTeam(role: string | null | undefined): 'wolf' | 'good' {
  return role === 'wolf' || role === 'wolf_king' ? 'wolf' : 'good'
}

/** 展示文档守卫：结构校验；v1 文档（无 is_night/stage/votes）明确拒绝，绝不静默降级。 */
export function parseDisplayDoc(value: unknown): DisplayDoc {
  if (typeof value !== 'object' || value === null) {
    throw new Error('文档不是合法 JSON 对象')
  }
  const v = value as Record<string, unknown>
  if (typeof v.match_id !== 'number' || !Array.isArray(v.segments)) {
    throw new Error('文档结构不完整：不是 whoisspy 导出文件')
  }
  if (v.view !== 'god' && v.view !== 'public') {
    throw new Error(`未知视角：${String(v.view)}`)
  }
  const m = v.match as Record<string, unknown> | undefined
  if (!m || !Array.isArray(m.seats)) {
    throw new Error('文档缺少 match.seats')
  }
  const segs = v.segments as Array<Record<string, unknown>>
  for (const seg of segs) {
    if (!Array.isArray(seg.entries) || typeof seg.stage !== 'object' || seg.stage === null) {
      throw new Error('文档版本不兼容：缺少 is_night/stage 字段，请用新版 CLI 重新导出')
    }
  }
  if (typeof v.usage !== 'object' || v.usage === null) {
    throw new Error('文档缺少 usage')
  }
  return value as DisplayDoc
}