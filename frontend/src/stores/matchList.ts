// 对局列表 store
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/client'
import type { MatchInfo } from '../model/types'

export const useMatchListStore = defineStore('matchList', () => {
  const matches = ref<MatchInfo[]>([])
  const loading = ref(false)

  async function refresh() {
    loading.value = true
    try {
      matches.value = await api.listMatches()
    } finally {
      loading.value = false
    }
  }

  return { matches, loading, refresh }
})
