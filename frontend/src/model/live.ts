// 直播帧 → 展示文档增量（docs/backend/15-serve.md 帧协议）
// 帧 = 展示文档的增量分解，append 进同一 DisplayDoc 模型（frontend.md 八）；
// 纯函数、可测，与后端 export 分段逻辑同构（不含任何游戏语义解释）。
import type {
  DisplayDoc,
  DisplaySegment,
  DisplayUsage,
  DisplayVoteRound,
  DisplaySeat,
} from './display'

export type LiveFrame = Record<string, unknown> & { type: string }

const EMPTY_USAGE: DisplayUsage = {
  calls: 0,
  prompt_tokens: 0,
  completion_tokens: 0,
  cached_prompt_tokens: 0,
  cost_micros: 0,
  cache_hit_rate: 0,
  fallbacks: 0,
  rule_errors: 0,
}

/** match_open 帧 → 空段展示文档（match 元信息与展示文档 match 字段同构）。 */
export function docFromMatchOpen(frame: LiveFrame): DisplayDoc {
  const match = frame.match as DisplayDoc['match'] & { match_id?: number }
  if (!match || !Array.isArray(match.seats)) {
    throw new Error('match_open 帧缺少 match 元信息')
  }
  const { match_id, ...matchRest } = match // match_id 属文档顶层，不在 match 字段内
  return {
    match_id: Number(match_id ?? frame.match_id ?? 0),
    exported_at: '',
    view: 'god', // serve 直播恒 god 视角
    match: { ...matchRest, seats: match.seats.map((s) => ({ ...s })) },
    segments: [],
    usage: { ...EMPTY_USAGE },
  }
}

/** 段内追加一行（segment_open 后、segment_close 前）。 */
export function appendLine(doc: DisplayDoc, frame: LiveFrame): void {
  const seg = lastSegment(doc)
  if (!seg) throw new Error('line 帧到达时尚无打开段')
  seg.entries.push({
    kind: String(frame.kind ?? ''),
    seat: frame.seat == null ? null : Number(frame.seat),
    text: String(frame.text ?? ''),
  })
}

/** segment_open：开新段；直播中的当前段沿用最近已知 stage（复盘态与静态导出一致）。 */
export function openSegment(doc: DisplayDoc, frame: LiveFrame): void {
  const last = lastSegment(doc)
  const stage = last
    ? { alive: [...last.stage.alive], sheriff: last.stage.sheriff }
    : { alive: [], sheriff: null }
  doc.segments.push({
    label: String(frame.label ?? ''),
    day_index: Number(frame.day_index ?? 0),
    is_night: Boolean(frame.is_night),
    entries: [],
    stage,
  })
}

/** segment_close：填当前段 stage/votes 快照（后端折叠口径，前端零解释）。 */
export function closeSegment(doc: DisplayDoc, frame: LiveFrame): void {
  const seg = lastSegment(doc)
  if (!seg) throw new Error('segment_close 帧到达时尚无打开段')
  const stage = frame.stage as { alive: number[]; sheriff: number | null } | undefined
  if (stage && Array.isArray(stage.alive)) {
    seg.stage = { alive: [...stage.alive], sheriff: stage.sheriff ?? null }
  }
  const votes = frame.votes as DisplayVoteRound[] | undefined
  if (Array.isArray(votes) && votes.length > 0) {
    seg.votes = votes
  }
}

/** 逐帧 apply（原地更新 doc，返回同一引用；类型不识别时静默忽略）。 */
export function applyFrame(doc: DisplayDoc, frame: LiveFrame): DisplayDoc {
  switch (frame.type) {
    case 'match_open':
      return docFromMatchOpen(frame)
    case 'segment_open':
      openSegment(doc, frame)
      break
    case 'line':
      appendLine(doc, frame)
      break
    case 'segment_close':
      closeSegment(doc, frame)
      break
    case 'seat_role': {
      const seat = Number(frame.seat)
      const row = doc.match.seats.find((s: DisplaySeat) => s.seat === seat)
      if (row) row.role = String(frame.role ?? '')
      break
    }
    case 'usage':
      doc.usage = { ...EMPTY_USAGE, ...omitType(frame) } as DisplayUsage
      break
    case 'finished':
      doc.match.status = 'finished'
      doc.match.winner = frame.winner == null ? null : String(frame.winner)
      doc.match.reason = frame.reason == null ? null : String(frame.reason)
      break
    case 'stopped':
      doc.match.status = 'stopped'
      doc.match.winner = null
      doc.match.reason = frame.reason == null ? null : String(frame.reason)
      break
    default:
      break // 未知帧类型静默忽略（协议向前兼容）
  }
  return doc
}

function lastSegment(doc: DisplayDoc): DisplaySegment | null {
  return doc.segments.length ? doc.segments[doc.segments.length - 1] : null
}

function omitType(frame: LiveFrame): Record<string, unknown> {
  const rest: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(frame)) {
    if (k !== 'type') rest[k] = v
  }
  return rest
}