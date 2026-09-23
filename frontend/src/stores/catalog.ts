// 目录 store：板子/人设预设
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/client'
import type { BoardPreset, Persona } from '../model/types'

export const useCatalogStore = defineStore('catalog', () => {
  const boards = ref<BoardPreset[]>([])
  const personas = ref<Persona[]>([])

  async function refresh() {
    try {
      const [b, p] = await Promise.all([api.boards(), api.personas()])
      boards.value = b
      personas.value = p
    } catch {
      /* 后端未起时静默，页面有兜底文案 */
    }
  }

  return { boards, personas, refresh }
})
