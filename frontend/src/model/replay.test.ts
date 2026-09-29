// 文档 → 视图纯投影测试（结构→视觉，无游戏语义）
import { describe, expect, it } from 'vitest'
import type { DisplayDoc, DisplaySegment } from './display'
import { buildSeats, clampSegment, lastVoteRound, speakingSeat } from './replay'
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