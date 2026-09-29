<script setup lang="ts">
// 中央对话剧场：整卷渲染全部段落，IntersectionObserver 上报当前段（纯渲染器，
// 不做视角过滤——文档本身已按视角生成，狼队频道/独白只在 god 文档存在）
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { DisplaySegment } from '../model/display'
import { mergeMonologues } from '../model/replay'
import type { Seat } from '../model/types'

const props = defineProps<{
  segments: DisplaySegment[]
  seats: Seat[]
}>()

const emit = defineEmits<{
  (e: 'segment-change', index: number): void
}>()

const scrollEl = ref<HTMLElement | null>(null)
const sectionEls: (HTMLElement | null)[] = []
let observer: IntersectionObserver | null = null

// 渲染用段：发言/频道/遗言后紧随的同座内心折叠进气泡（结构折叠，不改文本）
const mergedSegments = computed(() =>
  props.segments.map((s) => ({ ...s, entries: mergeMonologues(s.entries) })),
)

const seatById = new Map<number, Seat>(props.seats.map((s) => [s.id, s]))

function bindSection(el: unknown, index: number) {
  if (el instanceof HTMLElement) sectionEls[index] = el
}

function observe() {
  observer?.disconnect()
  if (!scrollEl.value) return
  observer = new IntersectionObserver(
    (entries) => {
      let best = -1
      let bestRatio = 0
      for (const en of entries) {
        if (en.isIntersecting && en.intersectionRatio > bestRatio) {
          bestRatio = en.intersectionRatio
          best = Number((en.target as HTMLElement).dataset.seg)
        }
      }
      if (best >= 0) emit('segment-change', best)
    },
    { root: scrollEl.value, threshold: [0.15, 0.4, 0.7] },
  )
  for (let i = 0; i < props.segments.length; i++) {
    const el = sectionEls[i]
    if (el) observer.observe(el)
  }
}

watch(
  () => props.segments,
  async () => {
    await nextTick()
    // 换文档（视角切换/换对局/本地重开）：滚动位置先归零，避免旧位置被
    // IntersectionObserver 当成新文档的当前段（进度条/木牌错乱）。
    if (scrollEl.value) scrollEl.value.scrollTop = 0
    observe()
  },
)

onMounted(async () => {
  await nextTick()
  observe()
})
onBeforeUnmount(() => observer?.disconnect())

/** 段落导航滚动（DirectorBar 调用）：按视口相对偏移计算，避免 offsetParent 干扰。 */
function scrollToSegment(index: number) {
  const el = sectionEls[index]
  const sc = scrollEl.value
  if (!el || !sc) return
  const top = el.getBoundingClientRect().top - sc.getBoundingClientRect().top + sc.scrollTop
  sc.scrollTo({ top, behavior: 'smooth' })
}

defineExpose({ scrollToSegment })
</script>

<template>
  <section ref="scrollEl" class="theater" aria-label="对局对话">
    <div
      v-for="(seg, si) in mergedSegments"
      :key="si"
      class="seg"
      :data-seg="si"
      :ref="(el) => bindSection(el, si)"
    >
      <p class="seg-label">{{ seg.label }}</p>
      <template v-for="(it, i) in seg.entries" :key="i">
        <!-- 段内阶段分隔行 -->
        <p v-if="it.kind === 'phase'" class="phase-divider">{{ it.text }}</p>

        <!-- 系统旁白 / 投票行 -->
        <p v-else-if="it.kind === 'system' || it.kind === 'vote'" class="narration">
          {{ it.text }}
        </p>

        <!-- 内心独白（独立动作：查验/投票/用药，无前置发言；仅 god 文档存在） -->
        <div v-else-if="it.kind === 'monologue'" class="mono-card">
          <span class="mono-tag">内心</span>
          <p class="mono-text">{{ it.text }}</p>
        </div>

        <!-- 狼队频道（仅 god 文档存在） -->
        <div v-else-if="it.kind === 'channel'" class="channel-row">
          <span class="mini-avatar">{{ seatById.get(it.seat ?? -1)?.emoji }}</span>
          <div class="bubble ch">
            <p class="who">
              {{ seatById.get(it.seat ?? -1)?.name }}
              <span class="tag wolf-tag">狼队频道</span>
            </p>
            <p class="text">{{ it.text }}</p>
            <p v-if="it.inner" class="inner">
              <span class="inner-tag">内心</span>
              <span class="inner-text">{{ it.inner.text }}</span>
            </p>
          </div>
        </div>

        <!-- 发言 / 遗言气泡 -->
        <div
          v-else
          class="bubble-row"
          :class="{ left: (seatById.get(it.seat ?? -1)?.side ?? 'L') === 'L' }"
        >
          <span class="mini-avatar">{{ seatById.get(it.seat ?? -1)?.emoji }}</span>
          <div class="bubble">
            <p class="who">
              {{ seatById.get(it.seat ?? -1)?.name }}
              <span v-if="it.kind === 'last_words'" class="tag last-tag">遗言</span>
              <span
                v-if="it.seat != null && seg.stage.sheriff === it.seat"
                class="tag sheriff-tag"
              >警长</span>
            </p>
            <p class="text">{{ it.text }}</p>
            <p v-if="it.inner" class="inner">
              <span class="inner-tag">内心</span>
              <span class="inner-text">{{ it.inner.text }}</span>
            </p>
          </div>
        </div>
      </template>
    </div>
    <p v-if="!segments.length" class="narration">没有内容（导出为空）</p>
  </section>
</template>

<style scoped>
.theater {
  min-height: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  border: var(--border-w) solid var(--ink);
  border-radius: var(--radius-lg);
  background: var(--paper);
  box-shadow: var(--shadow-pop);
  overflow-y: auto; /* 剧场内滚动（页面禁滚，见 frontend-design 布局） */
  overflow-x: hidden;
  scrollbar-width: thin;
  scrollbar-color: var(--paper-dim) transparent;
}
.seg {
  flex: none; /* 不收缩：内容超出时溢出形成滚动，而不是被压扁 */
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px 18px 18px;
  scroll-margin-top: 12px;
}
.seg + .seg {
  border-top: 2px dashed #c9bd9a;
}
.seg-label {
  align-self: center;
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 400;
  letter-spacing: 0.08em;
  color: #8a85a0;
  padding: 2px 12px;
  border: 2px solid #d8cfa9;
  border-radius: 999px;
  background: var(--paper-dim);
}

.phase-divider {
  align-self: center;
  font-size: 12px;
  font-weight: 700;
  color: #9b97a8;
  letter-spacing: 0.05em;
}

.narration {
  align-self: center;
  max-width: 92%;
  text-align: center;
  font-size: 13.5px;
  font-weight: 700;
  color: #6f6a85;
  padding: 6px 14px;
  background: var(--paper-dim);
  border-radius: 999px;
  border: 2px dashed #c9bd9a;
}

.bubble-row,
.channel-row {
  display: flex;
  gap: 9px;
  align-items: flex-end;
}
.bubble-row.left {
  flex-direction: row-reverse;
}

.mini-avatar {
  flex: none;
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  font-size: 22px;
  background: var(--paper-dim);
  border: 2.5px solid var(--ink);
  border-radius: 50%;
}

.bubble {
  max-width: 78%;
  background: #fff;
  border: 2.5px solid var(--ink);
  border-radius: 4px 16px 16px 16px;
  padding: 9px 13px 10px;
  box-shadow: 0 3px 0 var(--ink);
}
.bubble-row.left .bubble {
  border-radius: 16px 4px 16px 16px;
}

.who {
  font-size: 12px;
  font-weight: 900;
  color: #8a85a0;
  margin-bottom: 3px;
  display: flex;
  gap: 6px;
  align-items: center;
}
.bubble-row.left .who {
  justify-content: flex-end;
}

.tag {
  font-size: 10px;
  font-weight: 900;
  color: #fff;
  padding: 1px 7px;
  border-radius: 999px;
  border: 1.5px solid var(--ink);
}
.last-tag { background: var(--dead); }
.sheriff-tag { background: var(--sheriff); }
.wolf-tag { background: var(--wolf); }

.text {
  font-size: 14px;
  line-height: 1.62;
  white-space: pre-wrap;
  word-break: break-word;
}

/* 发言气泡内折叠的内心子块：虚线分隔 + 弱化色，与正文同框 */
.inner {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #d8cfa9;
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.inner-tag {
  flex: none;
  font-size: 10px;
  font-weight: 900;
  color: #55507a;
  border: 1.5px solid #9a92c4;
  border-radius: 6px;
  padding: 0 5px;
}
.inner-text {
  font-size: 12.5px;
  line-height: 1.55;
  color: #8a85a0;
}

.channel-row {
  justify-content: center;
}
.channel-row .bubble {
  max-width: 86%;
  background: #ffe9ef;
  border-color: var(--wolf);
  box-shadow: 0 3px 0 var(--wolf);
}
.channel-row .who {
  color: var(--wolf);
}

.mono-card {
  align-self: center;
  max-width: 88%;
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 8px 11px;
  background: #f3f0fa;
  border: 1.5px dashed #9a92c4;
  border-radius: 10px;
}
.mono-tag {
  flex: none;
  font-size: 10px;
  font-weight: 900;
  color: #55507a;
  border: 1.5px solid #9a92c4;
  border-radius: 6px;
  padding: 0 5px;
  margin-top: 1px;
}
.mono-text {
  font-size: 12.5px;
  line-height: 1.55;
  color: #55507a;
}
</style>