<script setup lang="ts">
// 预览导演条：设计稿阶段驱动章节推进（真实实现将由 SSE 驱动，此条退役）
defineProps<{
  chapterIndex: number
  chapterLabels: string[]
  autoplay: boolean
}>()
const emit = defineEmits<{
  (e: 'step', dir: 1 | -1): void
  (e: 'seek', idx: number): void
  (e: 'toggle-autoplay'): void
}>()
</script>

<template>
  <footer class="director" aria-label="预览控制">
    <button class="nav" aria-label="上一幕" @click="emit('step', -1)">‹</button>
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
    <button class="nav" aria-label="下一幕" @click="emit('step', 1)">›</button>
    <button class="play" :class="{ on: autoplay }" @click="emit('toggle-autoplay')">
      {{ autoplay ? '⏸ 暂停' : '▶ 自动播放' }}
    </button>
  </footer>
</template>

<style scoped>
.director {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 8px 18px 14px;
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
