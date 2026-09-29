// 复盘 store：展示文档 + 视角 + 段落游标（滚动驱动）
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { parseLocalFile } from '../source/localFile'
import { staticExportSource } from '../source/static'
import type { MatchSource } from '../source/MatchSource'
import type { DisplayDoc, View } from '../model/display'
import { clampSegment } from '../model/replay'

export const useReplayStore = defineStore('replay', () => {
  const doc = ref<DisplayDoc | null>(null)
  const view = ref<View>('god')
  const localMode = ref(false)
  const currentSegment = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const source: MatchSource = staticExportSource

  const segments = computed(() => doc.value?.segments ?? [])
  const segmentLabels = computed(() => segments.value.map((s) => s.label))
  const current = computed(() => segments.value[currentSegment.value] ?? null)
  const godView = computed(() => view.value === 'god')
  const finished = computed(() => doc.value?.match.status === 'finished')

  async function load(matchId: number | string, v: View) {
    loading.value = true
    error.value = null
    try {
      doc.value = await source.load(Number(matchId), v)
      view.value = doc.value.view
      localMode.value = false
      currentSegment.value = 0
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
      doc.value = null
    } finally {
      loading.value = false
    }
  }

  /** 本地文件打开（列表页调用后跳转 /matches/local）。 */
  async function loadLocal(file: File) {
    loading.value = true
    error.value = null
    try {
      doc.value = await parseLocalFile(file)
      view.value = doc.value.view
      localMode.value = true
      currentSegment.value = 0
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
      doc.value = null
    } finally {
      loading.value = false
    }
  }

  /** 视角切换 = 换文档重拉（本地文件态禁用）。 */
  function setView(v: View) {
    if (localMode.value || view.value === v || doc.value == null) return
    void load(doc.value.match_id, v)
  }

  function seek(index: number) {
    currentSegment.value = clampSegment(index, segments.value.length)
  }

  return {
    doc, view, localMode, currentSegment, loading, error,
    segments, segmentLabels, current, godView, finished,
    load, loadLocal, setView, seek,
  }
})