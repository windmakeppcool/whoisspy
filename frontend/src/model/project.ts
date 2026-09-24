// 事件→ViewModel 投影（纯函数，规则全在后端；Vitest 目标）
import type { GameEvent, MatchInfo, SeatInfo } from './types'
import { ROLE_NAMES } from './types'

export interface SeatVM {
  seat: number
  name: string
  model: string
  emoji: string
  role: string
  roleName: string
  team: 'wolf' | 'good'
  alive: boolean
}

export interface FeedItemVM {
  kind: 'speech' | 'channel' | 'last_words' | 'system' | 'monologue'
  seat?: number
  text: string
  monologue?: string
}

export interface VoteVM {
  title: string
  tally: Record<number, number>
  exile?: number
  tie: boolean
}

export interface MatchVM {
  phase: 'night' | 'day' | 'idle'
  day: number
  label: string
  seats: SeatVM[]
  feed: FeedItemVM[]
  sheriff: number | null
  vote: VoteVM | null
  finished: boolean
  winner: string | null
  resultReason: string | null
}

const PHASE_LABELS: Record<string, string> = {
  night_start: '夜幕降临', wolf_meeting: '狼队密谋', seer_check: '预言家行动',
  witch_turn: '女巫行动', sheriff_elect: '警长竞选', night_resolve: '夜间结算',
  speech_order: '发言定序', day_speech: '白天发言',
  day_vote: '放逐投票', exile_resolve: '放逐结算',
}

const SEAT_EMOJI = ['🦊', '🦉', '🐻', '🐱', '🦁', '🐰', '🐢', '🐮', '🐙', '🐧', '🦔', '🐝']

export function emptyVM(match: MatchInfo): MatchVM {
  return {
    phase: 'idle', day: 0, label: '等待开局', seats: match.seats.map(seatVM),
    feed: [], sheriff: null, vote: null, finished: false,
    winner: null, resultReason: null,
  }
}

export function seatVM(s: SeatInfo): SeatVM {
  const team = s.role === 'wolf' || s.role === 'wolf_king' ? 'wolf' : 'good'
  return {
    seat: s.seat, name: s.name, model: s.model,
    emoji: SEAT_EMOJI[(s.seat - 1) % SEAT_EMOJI.length],
    role: s.role, roleName: ROLE_NAMES[s.role] ?? '？？？',
    team, alive: true,
  }
}

export function applyEvent(vm: MatchVM, ev: GameEvent, godView: boolean): MatchVM {
  const p = ev.payload as Record<string, any>
  const next: MatchVM = { ...vm, seats: vm.seats.map(s => ({ ...s })), feed: [...vm.feed] }

  switch (ev.type) {
    case 'phase.started': {
      next.phase = String(p.phase).startsWith('night') || ['wolf_meeting', 'seer_check', 'witch_turn', 'night_resolve'].includes(String(p.phase)) ? 'night' : 'day'
      next.day = Number(p.day) || vm.day
      next.label = PHASE_LABELS[String(p.phase)] ?? String(p.phase)
      next.vote = null
      break
    }
    case 'role.dealt': {
      if (godView) {
        const s = next.seats.find(x => x.seat === Number(p.seat))
        if (s) {
          s.role = String(p.role)
          s.roleName = ROLE_NAMES[String(p.role)] ?? '？？？'
          s.team = p.role === 'wolf' || p.role === 'wolf_king' ? 'wolf' : 'good'
        }
      }
      break
    }
    case 'channel.round.started':
    case 'channel.round.ended':
      break // 频道边界由消息本身渲染
    case 'channel.message': {
      if (godView) {
        next.feed.push({ kind: 'channel', seat: Number(p.seat), text: String(p.text ?? '') })
      }
      break
    }
    case 'night.kill_target':
    case 'night.guard_target':
    case 'night.witch_action':
    case 'night.seer_query':
    case 'night.seer_result':
    case 'player.fallback':
    case 'player.monologue':
      break // 上帝视角细粒度信息 v1 暂不上屏（事件已入库可复盘）
    case 'night.resolved': {
      const deaths = (p.deaths ?? {}) as Record<string, string>
      for (const seat of Object.keys(deaths)) {
        const s = next.seats.find(x => x.seat === Number(seat))
        if (s) s.alive = false
      }
      const names = Object.keys(deaths).map(k => `${k}号`)
      next.feed.push({
        kind: 'system',
        text: names.length ? `🌙 第 ${ev.day_index} 夜结束——${names.join('、')}出局` : `🌙 第 ${ev.day_index} 夜结束——平安夜`,
      })
      break
    }
    case 'player.speech': {
      next.feed.push({ kind: 'speech', seat: Number(p.seat), text: String(p.text ?? '') })
      break
    }
    case 'player.last_words': {
      next.feed.push({ kind: 'last_words', seat: Number(p.seat), text: String(p.text ?? '') })
      break
    }
    case 'vote.cast':
      break
    case 'vote.resolved': {
      const votes = (p.votes ?? {}) as Record<string, number>
      const tally: Record<number, number> = {}
      for (const v of Object.values(votes)) {
        if (v) tally[v] = (tally[v] ?? 0) + 1
      }
      const exile = p.exiled ? Number(p.exiled) : undefined
      // scope=sheriff 是警长选举票，不是放逐票：只报结果、绝不判死（D27）
      if (p.scope === 'sheriff') {
        next.feed.push({
          kind: 'system',
          text: exile ? `🏅 警长投票：${exile}号得票最高` : '🏅 警长投票平票',
        })
        next.vote = { title: String(p.title ?? '警长投票'), tally, exile, tie: Boolean(p.tie) }
        break
      }
      if (exile) {
        const s = next.seats.find(x => x.seat === exile)
        if (s) s.alive = false
        next.feed.push({ kind: 'system', text: `⚖️ ${exile}号被放逐出局` })
      } else {
        next.feed.push({ kind: 'system', text: '🕊️ 平票 —— 平安日，无人出局' })
      }
      next.vote = { title: String(p.title ?? '放逐投票'), tally, exile, tie: Boolean(p.tie) }
      break
    }
    case 'day.speech_order': {
      const order = (p.order ?? []) as number[]
      if (order.length) {
        next.feed.push({ kind: 'system', text: `🗣️ 发言顺序：${order.join(' → ')}号` })
      }
      break
    }
    case 'gun.shoot': {
      const tgt = Number(p.target) || 0
      if (tgt) {
        const s = next.seats.find(x => x.seat === tgt)
        if (s) s.alive = false
        next.feed.push({ kind: 'system', text: `🔫 ${p.seat}号开枪带走了 ${tgt}号！` })
      } else {
        next.feed.push({ kind: 'system', text: `🔫 ${p.seat}号选择放弃开枪` })
      }
      break
    }
    case 'sheriff.registered':
      if ((p.seats ?? []).length) {
        next.sheriff = null
        next.feed.push({ kind: 'system', text: `🏅 上警：${(p.seats as number[]).join('、')}号` })
      } else {
        next.feed.push({ kind: 'system', text: '🏅 无人上警 —— 警徽丢失' })
      }
      break
    case 'sheriff.badge': {
      if (p.action === 'transfer' && p.to) {
        next.sheriff = Number(p.to)
        next.feed.push({ kind: 'system', text: `🏅 ${p.to}号当选警长` })
      } else {
        next.sheriff = null
        next.feed.push({ kind: 'system', text: '🏅 警徽被撕毁' })
      }
      break
    }
    case 'match.finished': {
      next.finished = true
      next.winner = String(p.winner ?? '')
      next.resultReason = String(p.reason ?? '')
      next.label = p.winner === 'wolf' ? '🐺 狼人阵营获胜' : '👍 好人阵营获胜'
      next.feed.push({ kind: 'system', text: `🏁 对局结束——${p.winner === 'wolf' ? '狼人阵营' : '好人阵营'}获胜（${p.reason}）` })
      break
    }
    case 'match.stopped': {
      next.finished = true
      next.label = '对局已终止'
      next.feed.push({ kind: 'system', text: '⏹️ 对局被终止' })
      break
    }
  }
  return next
}

export function projectAll(events: GameEvent[], match: MatchInfo, godView: boolean): MatchVM {
  let vm = emptyVM(match)
  for (const ev of events) vm = applyEvent(vm, ev, godView)
  return vm
}
