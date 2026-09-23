// match store：事件缓冲 + 投影 + SSE 生命周期
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../api/client'
import { connectStream, type SseHandle } from '../api/sse'
import { applyEvent, emptyVM, projectAll, type MatchVM } from '../model/project'
import type { GameEvent, MatchInfo, UsageSummary } from '../model/types'

export const useMatchStore = defineStore('match', () => {
  const match = ref<MatchInfo | null>(null)
  const events = ref<GameEvent[]>([])
  const godView = ref(true)
  const loading = ref(false)
  const usage = ref<UsageSummary | null>(null)
  let sse: SseHandle | null = null

  const vm = computed<MatchVM | null>(() => {
    if (!match.value) return null
    return events.value.reduce(
      (acc, ev) => applyEvent(acc, ev, godView.value),
      emptyVM(match.value),
    )
  })

  async function load(id: number | string) {
    loading.value = true
    sse?.close()
    match.value = await api.getMatch(id)
    events.value = await api.events(id, 0, godView.value ? 'god' : 'immersive')
    api.usage(id).then(u => (usage.value = u)).catch(() => {})
    loading.value = false
    if (match.value.status === 'created' || match.value.status === 'running') {
      subscribe()
    }
  }

  function subscribe() {
    if (!match.value) return
    sse = connectStream(
      match.value.id,
      godView.value ? 'god' : 'immersive',
      (ev) => {
        if (!events.value.some(e => e.seq === ev.seq)) {
          events.value.push(ev)
        }
      },
      () => {
        // 结束帧后拉最终状态与用量
        if (match.value) {
          api.getMatch(match.value.id).then(m => (match.value = m)).catch(() => {})
          api.usage(match.value.id).then(u => (usage.value = u)).catch(() => {})
        }
      },
    )
  }

  function toggleGod() {
    godView.value = !godView.value
    if (match.value) {
      // 视角切换 = 换过滤重新拉全量（服务端过滤是唯一权威）
      void load(match.value.id)
    }
  }

  async function stop() {
    if (match.value) await api.stop(match.value.id)
  }

  function dispose() {
    sse?.close()
    sse = null
  }

  return { match, events, godView, loading, usage, vm, load, toggleGod, stop, dispose, projectAll }
})
