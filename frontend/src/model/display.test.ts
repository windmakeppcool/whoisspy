// 展示文档守卫测试（schema 权威：docs/backend/11-export.md 第五节）
import { describe, expect, it } from 'vitest'
import { parseDisplayDoc } from './display'
import { boardLabel } from './types'
import fixture from './__fixtures__/match-god.json'

describe('parseDisplayDoc', () => {
  it('接受合法 v2 文档', () => {
    const doc = parseDisplayDoc(fixture)
    expect(doc.match_id).toBe(7)
    expect(doc.view).toBe('god')
    expect(doc.segments[1].stage.alive).toEqual([1])
    expect(doc.segments[1].votes?.[0].tally).toEqual({ '1': 1, '2': 1 })
  })

  it('拒绝 v1 文档（无 stage）——绝不静默降级', () => {
    const v1 = JSON.parse(JSON.stringify(fixture))
    delete v1.segments[0].stage
    expect(() => parseDisplayDoc(v1)).toThrow(/重新导出/)
  })

  it('拒绝非对象输入', () => {
    expect(() => parseDisplayDoc(null)).toThrow(/JSON/)
    expect(() => parseDisplayDoc('x')).toThrow(/JSON/)
  })

  it('拒绝未知视角', () => {
    const bad = JSON.parse(JSON.stringify(fixture))
    bad.view = 'spectator'
    expect(() => parseDisplayDoc(bad)).toThrow(/视角/)
  })

  it('拒绝缺 match.seats', () => {
    const bad = JSON.parse(JSON.stringify(fixture))
    delete bad.match.seats
    expect(() => parseDisplayDoc(bad)).toThrow(/match.seats/)
  })
})

describe('boardLabel', () => {
  it('standard 规则集显示全名', () => {
    expect(boardLabel('standard-12')).toBe('标准 12 人局')
    expect(boardLabel('standard-9')).toBe('标准 9 人局')
  })
  it('按人数求和兜底', () => {
    expect(boardLabel('minimal', { wolf: 3, seer: 1, witch: 1, hunter: 1, villager: 3 })).toBe('9 人局')
  })
})