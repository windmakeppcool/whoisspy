// 对局列表 store：消费静态导出源（exports/index.json）
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { MatchSummary } from '../model/display'
import { staticExportSource } from '../source/static'

export const useMatchListStore = defineStore('matchList', () => {
  const matches = ref<MatchSummary[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function refresh() {
    loading.value = true
    error.value = null
    try {
      matches.value = await staticExportSource.list()
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
      matches.value = []
    } finally {
      loading.value = false
    }
  }

  return { matches, loading, error, refresh }
})