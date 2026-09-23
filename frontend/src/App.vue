<script setup lang="ts">
// App：观赛页布局——顶栏 / 左右座位列 / 中央对话剧场 / 投票抽屉 / 天空场景
import { computed, onMounted, onUnmounted, ref } from 'vue'
import SkyBackdrop from './components/SkyBackdrop.vue'
import GameModeMenu from './components/GameModeMenu.vue'
import PhaseBanner from './components/PhaseBanner.vue'
import SeatColumn from './components/SeatColumn.vue'
import DialogueTheater from './components/DialogueTheater.vue'
import VoteDrawer from './components/VoteDrawer.vue'
import DirectorBar from './components/DirectorBar.vue'
import { MATCHES } from './mock/match'
import type { DemoState } from './model/types'

const matchIdx = ref(0)
const match = computed(() => MATCHES[matchIdx.value])
const chapterIndex = ref(0)
const godView = ref(true)
const autoplay = ref(false)
const state = ref<DemoState>(match.value.build(0))

// 把 deadSeats 应用到座位显示（mock 座位本身 alive 恒真）
const aliveSeats = computed(() => {
  const dead = new Set(state.value.deadSeats)
  return match.value.seats.map((s) => (dead.has(s.id) ? { ...s, alive: false } : s))
})
const leftSeats = computed(() => aliveSeats.value.filter((s) => s.side === 'L'))
const rightSeats = computed(() => aliveSeats.value.filter((s) => s.side === 'R'))
const chapterLabels = computed(() => match.value.chapters.map((c) => c.label))

// 说话座位 = 最近一条发言/频道消息的座位
const speakingSeat = computed(() => {
  const feed = state.value.feed
  for (let i = feed.length - 1; i >= 0; i--) {
    const kind = feed[i].kind
    if ((kind === 'speech' || kind === 'channel' || kind === 'last_words') && feed[i].seat != null) {
      return feed[i].seat!
    }
  }
  return null
})

function applyChapter() {
  state.value = match.value.build(chapterIndex.value)
}

function selectMode(mode: string) {
  const idx = MATCHES.findIndex((m) => m.mode === mode)
  if (idx >= 0 && idx !== matchIdx.value) {
    matchIdx.value = idx
    chapterIndex.value = 0
    applyChapter()
  }
}

function step(dir: 1 | -1) {
  const next = chapterIndex.value + dir
  if (next < 0 || next >= match.value.chapters.length) return
  chapterIndex.value = next
  applyChapter()
}

let timer: number | undefined
function toggleAutoplay() {
  autoplay.value = !autoplay.value
  if (timer) {
    clearInterval(timer)
    timer = undefined
  }
  if (autoplay.value) {
    timer = window.setInterval(() => {
      if (chapterIndex.value < match.value.chapters.length - 1) step(1)
      else toggleAutoplay()
    }, 2600)
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKey)
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
  if (timer) clearInterval(timer)
})
function onKey(e: KeyboardEvent) {
  if (e.key === 'ArrowRight') step(1)
  if (e.key === 'ArrowLeft') step(-1)
  if (e.key === 'g' || e.key === 'G') godView.value = !godView.value
}
</script>

<template>
  <div class="page">
    <SkyBackdrop :phase="state.phase" />
    <GameModeMenu
      :current-mode="match.mode"
      :god-view="godView"
      @select="selectMode"
      @toggle-god="godView = !godView"
    />

    <main class="stage">
      <aside class="wing" aria-label="左侧玩家">
        <SeatColumn
          :seats="leftSeats"
          side="L"
          :sheriff="state.sheriff"
          :god-view="godView"
          :speaking-seat="speakingSeat"
        />
      </aside>

      <div class="center">
        <PhaseBanner :phase="state.phase" :day="state.day" :label="state.label" />
        <DialogueTheater :state="state" :seats="aliveSeats" :god-view="godView" />
        <VoteDrawer :vote="state.vote" :seats="aliveSeats" />
      </div>

      <aside class="wing" aria-label="右侧玩家">
        <SeatColumn
          :seats="rightSeats"
          side="R"
          :sheriff="state.sheriff"
          :god-view="godView"
          :speaking-seat="speakingSeat"
        />
      </aside>
    </main>

    <DirectorBar
      :chapter-index="chapterIndex"
      :chapter-labels="chapterLabels"
      :autoplay="autoplay"
      @step="step"
      @seek="(i) => { chapterIndex = i; applyChapter() }"
      @toggle-autoplay="toggleAutoplay"
    />
  </div>
</template>

<style scoped>
.page {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.stage {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(170px, 230px) minmax(0, 1fr) minmax(170px, 230px);
  gap: 16px;
  padding: 2px 18px 4px;
  max-width: 1500px;
  width: 100%;
  margin: 0 auto;
}
.wing {
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  justify-content: center;
  scrollbar-width: none;
  padding: 6px 0;
}
.wing::-webkit-scrollbar {
  display: none;
}

.center {
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.center > :nth-child(2) {
  flex: 1;
  min-height: 0;
}

@media (max-width: 900px) {
  .stage {
    grid-template-columns: 1fr;
    grid-template-areas:
      'center'
      'wings';
  }
  .wing {
    display: none;
  }
  .wing:only-of-type {
    display: flex;
  }
  .center {
    grid-area: center;
  }
  .wing:first-of-type {
    grid-area: wings;
    flex-direction: row;
    flex-wrap: wrap;
    justify-content: center;
    overflow: visible;
  }
  .wing:last-of-type {
    display: none;
  }
}
</style>
