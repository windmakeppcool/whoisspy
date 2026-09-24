// 投影纯函数测试：事件流 → ViewModel（docs/milestones.md 前端测试项）
import { describe, expect, it } from 'vitest'
import { applyEvent, emptyVM, projectAll } from './project'
import type { GameEvent, MatchInfo } from './types'

const match: MatchInfo = {
  id: 1, game_type: 'werewolf', ruleset: 'minimal',
  board: { id: 'p6-classic', roles: { wolf: 2, seer: 1, villager: 3 } },
  rng_seed: 1, status: 'running', result: null, current_seq: 0,
  created_at: '',
  seats: Array.from({ length: 6 }, (_, i) => ({
    seat: i + 1, name: `p${i + 1}`, persona_id: 'calm', base_url: '',
    api_key_env: '', model: 'mock', role: '',
  })),
}

const ev = (seq: number, type: string, payload: Record<string, unknown>): GameEvent => ({
  seq, type, day_index: 1, phase: 'test', payload,
})

describe('project', () => {
  it('night.resolved 死亡标记座位并出旁白', () => {
    let vm = emptyVM(match)
    vm = applyEvent(vm, ev(1, 'night.resolved', { deaths: { 2: 'knife' } }), false)
    expect(vm.seats.find(s => s.seat === 2)?.alive).toBe(false)
    expect(vm.feed.some(f => f.kind === 'system' && f.text.includes('2号'))).toBe(true)
  })

  it('沉浸视角不渲染狼队频道', () => {
    let vm = emptyVM(match)
    vm = applyEvent(vm, ev(1, 'channel.message', { seat: 1, text: '刀3' }), false)
    expect(vm.feed).toHaveLength(0)
    vm = applyEvent(vm, ev(2, 'channel.message', { seat: 1, text: '刀3' }), true)
    expect(vm.feed).toHaveLength(1)
  })

  it('vote.resolved 平票出平安日旁白且无人死亡', () => {
    let vm = emptyVM(match)
    vm = applyEvent(vm, ev(1, 'vote.resolved', { votes: { 1: 2, 2: 1 }, exiled: null, tie: true }), false)
    expect(vm.vote?.tie).toBe(true)
    expect(vm.vote?.exile).toBeUndefined()
    expect(vm.seats.every(s => s.alive)).toBe(true)
    expect(vm.feed.some(f => f.text.includes('平安日'))).toBe(true)
  })

  it('vote.resolved 出局座位灰化', () => {
    let vm = emptyVM(match)
    vm = applyEvent(vm, ev(1, 'vote.resolved', { votes: { 1: 3, 2: 1 }, exiled: 3, tie: false }), false)
    expect(vm.seats.find(s => s.seat === 3)?.alive).toBe(false)
    expect(vm.vote?.exile).toBe(3)
  })

  it('match.finished 落胜负与理由', () => {
    let vm = emptyVM(match)
    vm = applyEvent(vm, ev(1, 'match.finished', { winner: 'wolf', reason: '第 8 天结束仍有狼存活' }), false)
    expect(vm.finished).toBe(true)
    expect(vm.winner).toBe('wolf')
    expect(vm.label).toContain('狼人阵营')
  })

  it('scope=sheriff 的选举票不判死（D27 回归）', () => {
    let vm = emptyVM(match)
    vm = applyEvent(vm, ev(1, 'vote.resolved',
      { votes: { 2: 1, 3: 1 }, scope: 'sheriff', title: '警长投票', exiled: 1, tie: false }), false)
    expect(vm.seats.every(s => s.alive)).toBe(true)   // 当选 ≠ 被放逐
    expect(vm.feed.some(f => f.text.includes('警长投票'))).toBe(true)
  })

  it('day.speech_order 出顺序旁白', () => {
    let vm = emptyVM(match)
    vm = applyEvent(vm, ev(1, 'day.speech_order',
      { order: [3, 4, 5, 1, 2], start: 3, decided_by: 'sheriff' }), false)
    expect(vm.feed.some(f => f.text.includes('发言顺序'))).toBe(true)
  })

  it('projectAll 全量回放与增量一致', () => {
    const events = [
      ev(1, 'phase.started', { phase: 'night_start', day: 1 }),
      ev(2, 'night.resolved', { deaths: {} }),
      ev(3, 'player.speech', { seat: 1, text: '大家好' }),
    ]
    const full = projectAll(events, match, false)
    let incremental = emptyVM(match)
    for (const e of events) incremental = applyEvent(incremental, e, false)
    expect(full).toEqual(incremental)
    expect(full.feed.some(f => f.kind === 'speech' && f.text === '大家好')).toBe(true)
  })
})

import { boardLabel } from './types'

describe('boardLabel', () => {
  it('standard 规则集显示全名', () => {
    expect(boardLabel('standard-12')).toBe('标准 12 人局')
    expect(boardLabel('standard-9')).toBe('标准 9 人局')
  })
  it('minimal 按人数求和', () => {
    expect(boardLabel('minimal', { wolf: 3, seer: 1, witch: 1, hunter: 1, villager: 3 })).toBe('9 人局')
  })
  it('无 counts 兜底极简局', () => {
    expect(boardLabel('minimal')).toBe('极简局')
  })
})
