<script setup lang="ts">
// 节奏控制条（pc-game 4.4 / 15-serve 三）：暂停/继续、逐帧、投递间隔
import { ref } from 'vue'

const props = defineProps<{
  paused: boolean
  disabled?: boolean
}>()
const emit = defineEmits<{
  (e: 'toggle'): void
  (e: 'frame'): void
  (e: 'speed', value: number): void
}>()

const SPEEDS = [
  { label: '实时', value: 0 },
  { label: '0.5s/帧', value: 0.5 },
  { label: '1s/帧', value: 1 },
  { label: '2s/帧', value: 2 },
]
const speed = ref(0)

function pick(value: number) {
  speed.value = value
  emit('speed', value)
}
</script>

<template>
  <div class="pace" aria-label="节奏控制">
    <button
      class="btn main"
      :class="{ on: props.paused }"
      :disabled="props.disabled"
      :title="props.paused ? '继续（pace resume）' : '暂停（pace pause）'"
      @click="emit('toggle')"
    >
      {{ props.paused ? '▶ 继续' : '⏸ 暂停' }}
    </button>
    <button
      class="btn"
      :disabled="props.disabled || !props.paused"
      :title="'逐帧推进一个事件（pace frame，暂停时可用）'"
      @click="emit('frame')"
    >
      ⏭ 逐帧
    </button>
    <span class="sep"></span>
    <button
      v-for="s in SPEEDS"
      :key="s.value"
      class="btn"
      :class="{ on: speed === s.value }"
      :disabled="props.disabled"
      :title="`帧投递间隔 ${s.label}（pace speed）`"
      @click="pick(s.value)"
    >
      {{ s.label }}
    </button>
  </div>
</template>

<style scoped>
.pace {
  display: flex;
  align-items: center;
  gap: 8px;
}
.btn {
  flex: none;
  padding: 7px 13px;
  font-size: 12.5px;
  font-weight: 900;
  background: var(--paper);
  border: var(--border-w) solid var(--ink);
  border-radius: 999px;
  box-shadow: var(--shadow-pop-sm);
}
.btn.main.on {
  background: var(--witch);
  color: #fff;
}
.btn.on {
  background: var(--ink);
  color: var(--paper);
}
.btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.sep {
  width: 1px;
  height: 20px;
  background: rgba(45, 42, 62, 0.25);
}
</style>