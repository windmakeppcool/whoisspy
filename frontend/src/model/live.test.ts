// 直播帧 → 展示文档增量（TDD）：docs/backend/15-serve.md 帧协议
// 核心验收：把静态导出文档反解成帧流 → applyFrame → 与 parseDisplayDoc 原文档一致
// （除 exported_at），锁死「直播帧 append 与复盘整文档同构」。
import { describe, expect, it } from 'vitest'
import { parseDisplayDoc, type DisplayDoc } from './display'
import {
  applyFrame,
  docFromMatchOpen,
  type LiveFrame,
} from './live'
import fixture from './__fixtures__/match-god.json'

/** 展示文档 → 帧流（与后端 15-serve 推送同构的反解）。 */
function framesFromDoc(doc: DisplayDoc): LiveFrame[] {
  const frames: LiveFrame[] = [
    {
      type: 'match_open',
      match_id: doc.match_id,
      match: { ...doc.match, match_id: doc.match_id },
    },
  ]
  for (const seg of doc.segments) {
    frames.push({
      type: 'segment_open',
      label: seg.label,
      day_index: seg.day_index,
      is_night: seg.is_night,
    })
    for (const e of seg.entries) {
      frames.push({ type: 'line', kind: e.kind, seat: e.seat, text: e.text })
    }
    const close: LiveFrame = { type: 'segment_close', stage: seg.stage }
    if (seg.votes) close.votes = seg.votes
    frames.push(close)
  }
  frames.push({ type: 'usage', ...doc.usage })
  if (doc.match.status === 'finished') {
    frames.push({
      type: 'finished',
      winner: doc.match.winner,
      reason: doc.match.reason,
    })
  }
  return frames
}

function build(doc: DisplayDoc): DisplayDoc {
  let out: DisplayDoc | null = null
  for (const f of framesFromDoc(doc)) {
    out = applyFrame(out ?? (null as unknown as DisplayDoc), f)
  }
  return out as DisplayDoc
}

describe('直播帧增量', () => {
  it('帧流重建 ≡ 静态导出文档（exported_at 除外）', () => {
    const doc = parseDisplayDoc(fixture)
    const rebuilt = build(doc)
    const { exported_at: _a, ...expectRest } = JSON.parse(JSON.stringify(doc)) as Record<
      string,
      unknown
    >
    const { exported_at: _b, ...gotRest } = JSON.parse(JSON.stringify(rebuilt)) as Record<
      string,
      unknown
    >
    expect(gotRest).toEqual(expectRest)
  })

  it('match_open 初始化文档（match_id 归顶层）', () => {
    const doc = parseDisplayDoc(fixture)
    const out = docFromMatchOpen(framesFromDoc(doc)[0])
    expect(out.match_id).toBe(doc.match_id)
    expect(out.match.seats[0].role).toBe('seer')
    expect(out.segments).toEqual([])
    expect(out.view).toBe('god')
  })

  it('line 在无打开段时报错', () => {
    const doc = parseDisplayDoc(fixture)
    const out = docFromMatchOpen(framesFromDoc(doc)[0])
    expect(() => applyFrame(out, { type: 'line', kind: 'system', seat: null, text: 'x' }))
      .toThrow()
  })

  it('segment_close 填当前段 stage/votes', () => {
    const doc = parseDisplayDoc(fixture)
    const out = docFromMatchOpen(framesFromDoc(doc)[0])
    applyFrame(out, { type: 'segment_open', label: '开局', day_index: 0, is_night: false })
    applyFrame(out, { type: 'segment_close', stage: { alive: [1], sheriff: null } })
    expect(out.segments[0].stage).toEqual({ alive: [1], sheriff: null })
    // 未开段的 close 报错
    const empty = docFromMatchOpen(framesFromDoc(doc)[0])
    expect(() => applyFrame(empty, { type: 'segment_close', stage: {} })).toThrow()
  })

  it('seat_role 刷新 match.seats[].role', () => {
    const doc = parseDisplayDoc(fixture)
    const out = docFromMatchOpen(framesFromDoc(doc)[0])
    applyFrame(out, { type: 'seat_role', seat: 1, role: 'witch' })
    expect(out.match.seats[0].role).toBe('witch')
  })

  it('usage 帧覆盖用量字段', () => {
    const doc = parseDisplayDoc(fixture)
    const out = docFromMatchOpen(framesFromDoc(doc)[0])
    applyFrame(out, { type: 'usage', calls: 9, prompt_tokens: 100, rule_errors: 1 })
    expect(out.usage.calls).toBe(9)
    expect(out.usage.prompt_tokens).toBe(100)
    expect(out.usage.rule_errors).toBe(1)
  })

  it('finished/stopped 收尾状态', () => {
    const doc = parseDisplayDoc(fixture)
    const out = docFromMatchOpen(framesFromDoc(doc)[0])
    applyFrame(out, { type: 'finished', winner: 'wolf', reason: '狼人获胜' })
    expect(out.match.status).toBe('finished')
    expect(out.match.winner).toBe('wolf')
    applyFrame(out, { type: 'stopped', reason: '手动终止' })
    expect(out.match.status).toBe('stopped')
    expect(out.match.winner).toBeNull()
  })

  it('未知帧类型静默忽略', () => {
    const doc = parseDisplayDoc(fixture)
    const out = docFromMatchOpen(framesFromDoc(doc)[0])
    const before = JSON.stringify(out)
    applyFrame(out, { type: 'input_required', seat: 3 })
    expect(JSON.stringify(out)).toBe(before)
  })

  it('直播中当前段沿用最近已知 stage（占位不闪空）', () => {
    const doc = parseDisplayDoc(fixture)
    const out = docFromMatchOpen(framesFromDoc(doc)[0])
    applyFrame(out, { type: 'segment_open', label: '开局', day_index: 0, is_night: false })
    applyFrame(out, { type: 'segment_close', stage: { alive: [1, 2], sheriff: 1 } })
    applyFrame(out, { type: 'segment_open', label: '第一天', day_index: 1, is_night: false })
    expect(out.segments[1].stage).toEqual({ alive: [1, 2], sheriff: 1 })
  })
})