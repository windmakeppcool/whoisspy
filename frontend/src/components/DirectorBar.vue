<script setup lang="ts">
// 段落导航条：章节胶囊 = 导出文档 segments；顶部细进度条 = 复盘进度；
// 当前段数字「N / M」；自动播放暂缓（roadmap）
import { computed } from 'vue'

const props = defineProps<{
  chapterIndex: number
  chapterLabels: string[]
  autoplay?: boolean
  showAutoplay?: boolean
}>()
const emit = defineEmits<{
  (e: 'step', dir: 1 | -1): void
  (e: 'seek', idx: number): void
  (e: 'toggle-autoplay'): void
}>()

// 进度百分比：已到第 N 段 / 共 M 段（无段落时为 0）
const pct = computed(() => {
  const total = props.chapterLabels.length
  return total > 0 ? Math.round(((props.chapterIndex + 1) / total) * 100) : 0
})
</script>

<template>
  <footer class="director" aria-label="段落导航">
    <div
      class="progress-track"
      role="progressbar"
      :aria-valuenow="pct"
      aria-valuemin="0"
      aria-valuemax="100"
      aria-label="复盘进度"
    >
      <div class="progress-fill" :style="{ width: pct + '%' }"></div>
    </div>
    <div class="row">
      <button class="nav" aria-label="上一段" @click="emit('step', -1)">‹</button>
      <div class="chapters">
        <button
          v-for="(label, i) in chapterLabels"
          :key="i"
          class="chapter"
          :class="{ now: i === chapterIndex, done: i < chapterIndex }"
          @click="emit('seek', i)"
        >
          {{ label }}
        </button>
      </div>
      <span class="pos" aria-label="当前段落">{{ chapterIndex + 1 }} / {{ chapterLabels.length }}</span>
      <button class="nav" aria-label="下一段" @click="emit('step', 1)">›</button>
      <button
        v-if="showAutoplay"
        class="play"
        :class="{ on: autoplay }"
        @click="emit('toggle-autoplay')"
      >
        {{ autoplay ? '⏸ 暂停' : '▶ 自动播放' }}
      </button>
    </div>
  </footer>
</template>

<style scoped>
.director {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 6px 18px 12px;
}
/* 进度条：命名避开 VoteDrawer 的 .track（投票条），防止类名歧义 */
.progress-track {
  position: relative;
  height: 8px;
  background: var(--paper-dim);
  border: var(--border-w) solid var(--ink);
  border-radius: 999px;
  box-shadow: inset 0 2px 0 rgba(45, 42, 62, 0.15);
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--sheriff) 0%, #7d7894 100%);
  border-radius: 999px;
  transition: width 0.25s ease;
}
.row {
  display: flex;
  align-items: center;
  gap: 9px;
}
.nav {
  flex: none;
  width: 34px;
  height: 34px;
  font-size: 19px;
  font-weight: 900;
  background: var(--paper);
  border: var(--border-w) solid var(--ink);
  border-radius: 50%;
  box-shadow: var(--shadow-pop-sm);
}
.nav:hover {
  background: var(--paper-dim);
}
.chapters {
  flex: 1;
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding: 3px;
  scrollbar-width: none;
}
.chapter {
  flex: none;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
  background: var(--paper);
  border: 2px solid var(--ink);
  border-radius: 999px;
  color: #7d7894;
}
.chapter.done {
  background: var(--paper-dim);
  color: var(--ink);
}
.chapter.now {
  background: var(--ink);
  color: var(--paper);
  box-shadow: 0 2px 0 rgba(45, 42, 62, 0.4);
}
.pos {
  flex: none;
  font-family: var(--font-num);
  font-size: 13px;
  font-weight: 800;
  color: var(--ink);
  background: var(--paper);
  border: var(--border-w) solid var(--ink);
  border-radius: 999px;
  padding: 4px 10px;
  box-shadow: var(--shadow-pop-sm);
}
.play {
  flex: none;
  padding: 7px 14px;
  font-size: 13px;
  font-weight: 900;
  background: var(--paper);
  border: var(--border-w) solid var(--ink);
  border-radius: 999px;
  box-shadow: var(--shadow-pop-sm);
}
.play.on {
  background: var(--witch);
  color: #fff;
}
</style>
