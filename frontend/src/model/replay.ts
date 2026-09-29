// 文档 → 视图 props 的纯投影（结构→视觉，无任何游戏语义；P5 只禁事件解释）
import { SEAT_EMOJI, roleTeam, type DisplayDoc, type DisplaySegment } from './display'
import type { Seat, VoteRound } from './types'

/** 文档座位 + 段末快照 → 座位卡 props（存活/警长随当前段变化）。 */
export function buildSeats(
  doc: DisplayDoc,
  stage: DisplaySegment['stage'],
): Seat[] {
  const half = Math.ceil(doc.match.seats.length / 2)
  return doc.match.seats.map((s, i) => ({
    id: s.seat,
    name: s.persona_name,
    persona: s.persona_style,
    model: s.model,
    emoji: SEAT_EMOJI[(s.seat - 1) % SEAT_EMOJI.length],
    role: (s.role || 'villager') as Seat['role'],
    team: roleTeam(s.role),
    alive: stage.alive.includes(s.seat),
    side: i < half ? 'L' : 'R',
  }))
}

/** JSON 键字符串 → number 归一（03-events 不变量 3）。 */
function numRecord(r: Record<string, number>): Record<number, number> {
  const out: Record<number, number> = {}
  for (const k of Object.keys(r)) out[Number(k)] = r[k]
  return out
}

/** 段内投票回合 → VoteDrawer props（取段内最后一回合）。 */
export function lastVoteRound(seg: DisplaySegment): VoteRound | null {
  const rounds = seg.votes
  if (!rounds || rounds.length === 0) return null
  const v = rounds[rounds.length - 1]
  return {
    day: seg.day_index,
    title: v.title,
    tally: numRecord(v.tally),
    exile: v.exiled ?? undefined,
  }
}

/** 当前段内最后一条带座位的发言（弹起动画的纯视觉派生）。 */
export function speakingSeat(seg: DisplaySegment): number | null {
  for (let i = seg.entries.length - 1; i >= 0; i--) {
    const e = seg.entries[i]
    if (
      (e.kind === 'speech' || e.kind === 'channel' || e.kind === 'last_words') &&
      e.seat != null
    ) {
      return e.seat
    }
  }
  return null
}

export function clampSegment(index: number, count: number): number {
  if (count <= 0) return 0
  return Math.min(Math.max(index, 0), count - 1)
}