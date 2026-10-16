// 直播 store：ApiSource 帧流 → 展示文档（观战 = 零人类座位，档 1）
import { defineStore } from 'pinia'
import { computed, ref, type Ref } from 'vue'
import { applyFrame, docFromMatchOpen, type LiveFrame } from '../model/live'
import type { DisplayDoc } from '../model/display'
import { ApiSource, apiOptionsFromEnv, type PaceOp } from '../source/api'

declare global {
  interface Window {
    // Electron preload 注入的 sidecar 连接信息（pc-game 二）
    whoisspy?: { port?: number; token?: string }
  }
}

export const useLiveStore = defineStore('live', () => {
  // 显式 Ref 标注：ref<T>() 的 UnwrapRef 会展开 class 实例（丢失私有字段）
  const api: Ref<ApiSource | null> = ref(null)
  const doc = ref<DisplayDoc | null>(null)
  const connected = ref(false)
  const paused = ref(false)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const resyncing = ref(false) // 重连后等待 snapshot 期间丢弃旧帧
  const currentSegment = ref(0)

  const segments = computed(() => doc.value?.segments ?? [])
  const segmentLabels = computed(() => segments.value.map((s) => s.label))
  const current = computed(() => segments.value[currentSegment.value] ?? null)
  const finished = computed(() => doc.value?.match.status === 'finished')
  const stopped = computed(() => doc.value?.match.status === 'stopped')

  /** 应用启动时初始化（无注入/env 配置则返回 false，前端保持纯复盘模式）。 */
  async function setup(): Promise<boolean> {
    if (api.value) return true
    const opts = apiOptionsFromEnv(window.whoisspy, import.meta.env as Record<string, string | undefined>)
    if (!opts) return false
    const source = new ApiSource(opts)
    source.onFrame(onFrame)
    try {
      await source.connect()
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
      return false
    }
    api.value = source
    connected.value = true
    error.value = null
    return true
  }

  /** 帧 → 展示文档增量；直播中当前段自动跟随最新。 */
  function onFrame(frame: LiveFrame) {
    if (resyncing.value) return // snapshot 到达前的旧帧丢弃
    if (!doc.value) {
      if (frame.type === 'match_open') {
        doc.value = docFromMatchOpen(frame)
        currentSegment.value = 0
      }
      return
    }
    applyFrame(doc.value, frame)
    currentSegment.value = doc.value.segments.length - 1
  }

  /** 建局（观战 = 全 LLM 座位）。 */
  async function createMatch(opts: { seed?: number; paused?: boolean } = {}): Promise<number> {
    const source = await requireApi()
    loading.value = true
    error.value = null
    resyncing.value = false
    doc.value = null
    try {
      const mid = await source.createMatch(opts)
      paused.value = !!opts.paused
      return mid
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
      throw e
    } finally {
      loading.value = false
    }
  }

  /** 全量快照（断线恢复/窗口重开）。 */
  async function sync() {
    const source = await requireApi()
    resyncing.value = true
    try {
      doc.value = await source.sync()
      paused.value = false
      currentSegment.value = doc.value.segments.length - 1
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
      throw e
    } finally {
      resyncing.value = false
    }
  }

  /** 节奏控制（15-serve 三）。 */
  async function pace(op: PaceOp, value?: number) {
    const source = await requireApi()
    await source.pace(op, value)
    if (op === 'pause') paused.value = true
    else if (op === 'resume') paused.value = false
  }

  async function requireApi(): Promise<ApiSource> {
    if (!api.value) {
      const ok = await setup()
      if (!ok || !api.value) throw new Error(error.value ?? '未连接对局引擎')
    }
    return api.value
  }

  function disconnect() {
    api.value?.close()
    api.value = null
    connected.value = false
  }

  return {
    doc, connected, paused, loading, error, currentSegment,
    segments, segmentLabels, current, finished, stopped,
    setup, createMatch, sync, pace, disconnect,
  }
})