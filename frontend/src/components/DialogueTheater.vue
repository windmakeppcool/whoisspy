<script setup lang="ts">
// 中央对话剧场：系统旁白、公开发言、狼队频道（god）、遗言，底部自动跟随
import { computed, ref, watch, nextTick } from 'vue'
import type { DemoState, Seat } from '../model/types'

const props = defineProps<{
  state: DemoState
  seats: Seat[]
  godView: boolean
}>()

const scrollEl = ref<HTMLElement | null>(null)

const seatById = computed(() => {
  const m = new Map<number, Seat>()
  for (const s of props.seats) m.set(s.id, s)
  return m
})

// 过滤：沉浸视角看不到狼队频道与内心独白
const visibleFeed = computed(() =>
  props.state.feed.filter((it) => {
    if (it.kind === 'channel') return props.godView
    if (it.monologue && !props.godView) return { ...it, monologue: undefined }
    return true
  }),
)
const visibleItems = computed(() =>
  visibleFeed.value.map((it) => (props.godView ? it : { ...it, monologue: undefined })),
)

const sheriffName = computed(() => {
  if (props.state.sheriff == null) return null
  return seatById.value.get(props.state.sheriff)?.name ?? null
})

const seatOf = (id?: number) => (id == null ? undefined : seatById.value.get(id))

watch(
  () => props.state.feed.length,
  async () => {
    await nextTick()
    scrollEl.value?.scrollTo({ top: scrollEl.value.scrollHeight, behavior: 'smooth' })
  },
)
</script>

<template>
  <section class="theater" aria-label="对局对话">
    <div ref="scrollEl" class="feed">
      <template v-for="(it, i) in visibleItems" :key="i">
        <!-- 系统旁白 -->
        <p v-if="it.kind === 'system'" class="narration">{{ it.text }}</p>

        <!-- 发言气泡（含遗言样式） -->
        <div
          v-else-if="it.kind === 'speech' || it.kind === 'last_words'"
          class="bubble-row"
          :class="{ left: (seatOf(it.seat)?.side ?? 'L') === 'L', last: it.kind === 'last_words' }"
        >
          <span class="mini-avatar">{{ seatOf(it.seat)?.emoji }}</span>
          <div class="bubble">
            <p class="who">
              {{ seatOf(it.seat)?.id }}号 · {{ seatOf(it.seat)?.name }}
              <span v-if="it.kind === 'last_words'" class="tag last-tag">遗言</span>
              <span v-if="sheriffName === seatOf(it.seat)?.name" class="tag sheriff-tag">警长</span>
            </p>
            <p class="text">{{ it.text }}</p>
            <p v-if="it.monologue" class="mono">
              <span class="mono-tag">内心</span>{{ it.monologue }}
            </p>
          </div>
        </div>

        <!-- 狼队频道（仅上帝视角） -->
        <div v-else-if="it.kind === 'channel'" class="channel-row">
          <div class="channel-bubble">
            <p class="who">
              {{ seatOf(it.seat)?.emoji }} {{ seatOf(it.seat)?.id }}号 · {{ seatOf(it.seat)?.name }}
              <span class="tag wolf-tag">狼队频道</span>
            </p>
            <p class="text">{{ it.text }}</p>
            <p v-if="it.monologue" class="mono"><span class="mono-tag">内心</span>{{ it.monologue }}</p>
          </div>
        </div>
      </template>
    </div>
  </section>
</template>

<style scoped>
.theater {
  min-height: 0;
  display: flex;
  flex-direction: column;
  border: var(--border-w) solid var(--ink);
  border-radius: var(--radius-lg);
  background: var(--paper);
  box-shadow: var(--shadow-pop);
  overflow: hidden;
}

.feed {
  flex: 1;
  overflow-y: auto;
  padding: 16px 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  scrollbar-width: thin;
  scrollbar-color: var(--paper-dim) transparent;
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
.bubble-row.right {
  flex-direction: row-reverse;
}
.bubble-row.right .who {
  text-align: right;
}
.bubble-row.left .who {
  text-align: left;
}
.bubble-row.right .mono {
  text-align: left;
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
.bubble-row.right .bubble {
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
.bubble-row.right .who {
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

.mono {
  margin-top: 7px;
  padding: 7px 9px;
  background: #f3f0fa;
  border: 1.5px dashed #9a92c4;
  border-radius: 9px;
  font-size: 12px;
  line-height: 1.55;
  color: #55507a;
  display: flex;
  gap: 6px;
  align-items: baseline;
}
.mono-tag {
  flex: none;
  font-size: 10px;
  font-weight: 900;
  color: #55507a;
  border: 1.5px solid #9a92c4;
  border-radius: 6px;
  padding: 0 5px;
}

.channel-row {
  justify-content: center;
}
.channel-bubble {
  max-width: 86%;
  background: #ffe9ef;
  border: 2.5px solid var(--wolf);
  border-radius: 14px;
  padding: 9px 13px 10px;
  box-shadow: 0 3px 0 var(--wolf);
}
.channel-bubble .who {
  color: var(--wolf);
}
</style>
