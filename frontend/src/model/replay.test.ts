// 文档 → 视图纯投影测试（结构→视觉，无游戏语义）
import { describe, expect, it } from 'vitest'
import type { DisplayDoc, DisplaySegment, DisplayEntry } from './display'
import {
  buildSeats, clampSegment, lastVoteRound, mergeMonologues, speakingSeat,
} from './replay'
import fixture from './__fixtures__/match-god.json'

const doc = fixture as unknown as DisplayDoc

describe('buildSeats', () => {
  it('按段快照映射存活/角色/阵营/人设名', () => {
    const seats = buildSeats(doc, { alive: [1], sheriff: null })
    expect(seats).toHaveLength(2)
    expect(seats[0].alive).toBe(true)
    expect(seats[1].alive).toBe(false)
    expect(seats[0].role).toBe('seer')
    expect(seats[1].team).toBe('wolf')
    expect(seats[0].name).toBe('悍跳强攻型')
    expect(seats[0].side).toBe('L')
    expect(seats[1].side).toBe('R')
  })
})

describe('lastVoteRound', () => {
  it('取段内最后一回合并把键归一为 number', () => {
    const seg = doc.segments[1] as DisplaySegment
    const v = lastVoteRound(seg)
    expect(v?.title).toBe('放逐投票')
    expect(v?.tally).toEqual({ 1: 1, 2: 1 })
    expect(v?.exile).toBe(2)
  })
  it('无票回合返回 null', () => {
    expect(lastVoteRound(doc.segments[0] as DisplaySegment)).toBeNull()
  })
})

describe('speakingSeat', () => {
  it('取段内最后一条发言座位', () => {
    expect(speakingSeat(doc.segments[1] as DisplaySegment)).toBe(2)
  })
  it('无发言返回 null', () => {
    expect(speakingSeat(doc.segments[0] as DisplaySegment)).toBeNull()
  })
})

describe('clampSegment', () => {
  it('钳制越界', () => {
    expect(clampSegment(-1, 2)).toBe(0)
    expect(clampSegment(5, 2)).toBe(1)
    expect(clampSegment(1, 2)).toBe(1)
    expect(clampSegment(0, 0)).toBe(0)
  })
})

describe('mergeMonologues', () => {
  const e = (kind: string, seat: number | null, text: string): DisplayEntry =>
    ({ kind, seat, text })

  it('发言后紧跟同座内心 → 合并进一条（inner 携带内心，原内心被消费）', () => {
    const out = mergeMonologues([
      e('speech', 1, '1 号：我是预言家'),
      e('monologue', 1, '1 号（内心）：真预言家起跳'),
    ])
    expect(out).toHaveLength(1)
    expect(out[0]).toEqual({
      kind: 'speech', seat: 1, text: '1 号：我是预言家',
      inner: { text: '1 号（内心）：真预言家起跳' },
    })
  })

  it('狼队频道后紧跟同座内心 → 合并', () => {
    const out = mergeMonologues([
      e('channel', 6, '6 号（狼队频道）：刀 1 号'),
      e('monologue', 6, '6 号（内心）：按 kill 行动'),
    ])
    expect(out).toHaveLength(1)
    expect(out[0].inner?.text).toBe('6 号（内心）：按 kill 行动')
  })

  it('遗言后紧跟同座内心 → 合并', () => {
    const out = mergeMonologues([
      e('last_words', 9, '9 号（遗言）：我是狼'),
      e('monologue', 9, '9 号（内心）：暴露了'),
    ])
    expect(out).toHaveLength(1)
    expect(out[0].kind).toBe('last_words')
    expect(out[0].inner?.text).toBe('9 号（内心）：暴露了')
  })

  it('内心前不是发言（独立动作内心）→ 保留独立卡，inner 为 null', () => {
    const out = mergeMonologues([
      e('system', null, '预言家查验 2 号'),
      e('monologue', 1, '1 号（内心）：按 check 行动'),
    ])
    expect(out).toHaveLength(2)
    expect(out[1]).toEqual({ kind: 'monologue', seat: 1, text: '1 号（内心）：按 check 行动', inner: null })
  })

  it('内心紧跟的是别人发言（不同座）→ 不合并，各自独立', () => {
    const out = mergeMonologues([
      e('speech', 1, '1 号：我踩 2 号'),
      e('monologue', 2, '2 号（内心）：这刀必须落'),
    ])
    expect(out).toHaveLength(2)
    expect(out[0].inner).toBeNull()
    expect(out[1].inner).toBeNull()
  })

  it('非发言类条目原样透传，inner 为 null', () => {
    const out = mergeMonologues([
      e('phase', null, '—— 入夜 ——'),
      e('vote', 1, '1 号投票给 2 号'),
    ])
    expect(out).toHaveLength(2)
    expect(out[0]).toEqual({ kind: 'phase', seat: null, text: '—— 入夜 ——', inner: null })
    expect(out[1].inner).toBeNull()
  })

  it('fixture 段1：1 号发言内心合并、2 号发言无内心独立（顺序与条数守恒）', () => {
    const seg = doc.segments[1] as DisplaySegment
    const out = mergeMonologues(seg.entries)
    expect(out).toHaveLength(seg.entries.length - 1)
    const first = out[1]
    expect(first.kind).toBe('speech')
    expect(first.seat).toBe(1)
    expect(first.inner?.text).toContain('内心')
    const second = out[2]
    expect(second.kind).toBe('speech')
    expect(second.seat).toBe(2)
    expect(second.inner).toBeNull()
  })
})