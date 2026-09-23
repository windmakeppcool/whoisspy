<script setup lang="ts">
// 观赛/复盘页：MatchStage 渲染 store 投影，SSE 增量追更（观赛与历史共用本组件）
import { computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useMatchStore } from '../stores/match'
import { api } from '../api/client'
import { boardLabel } from '../model/types'
import GameModeMenu from '../components/GameModeMenu.vue'
import PhaseBanner from '../components/PhaseBanner.vue'
import SeatColumn from '../components/SeatColumn.vue'
import VoteDrawer from '../components/VoteDrawer.vue'

const route = useRoute()
const store = useMatchStore()

onMounted(() => void store.load(route.params.id as string))
onUnmounted(() => store.dispose())
watch(() => route.params.id, (id) => { if (id) void store.load(id as string) })

const vm = computed(() => store.vm)

// 投影 VM → 设计稿组件 props
import type { Seat } from '../model/types'
import type { FeedItem } from '../model/types'
import type { VoteRound } from '../model/types'

const seats = computed<Seat[]>(() =>
  ((vm.value?.seats ?? []) as any[]).map((s: any, i: number): Seat => ({
    id: s.seat, name: s.name, persona: '', model: s.model, emoji: s.emoji,
    role: (s.role || 'villager') as Seat['role'],
    team: s.team, alive: s.alive, side: (i < Math.ceil(((vm.value?.seats ?? []).length) / 2) ? 'L' : 'R'),
  })),
)
const leftSeats = computed(() => seats.value.filter(s => s.side === 'L'))
const rightSeats = computed(() => seats.value.filter(s => s.side === 'R'))

const demoState = computed(() => ({
  phase: (vm.value?.phase === 'night' ? 'night' : 'day') as 'night' | 'day',
  day: vm.value?.day ?? 1,
  label: vm.value?.label ?? '',
  feed: (vm.value?.feed ?? []) as FeedItem[],
  sheriff: vm.value?.sheriff ?? null,
  vote: (vm.value?.vote
    ? { day: vm.value.day, title: vm.value.vote.title, tally: vm.value.vote.tally, exile: vm.value.vote.exile }
    : null) as VoteRound | null,
  deadSeats: (vm.value?.seats ?? []).filter(s => !s.alive).map(s => s.seat),
}))

const speakingSeat = computed(() => {
  const feed = demoState.value.feed
  for (let i = feed.length - 1; i >= 0; i--) {
    const k = feed[i].kind
    if ((k === 'speech' || k === 'channel' || k === 'last_words') && feed[i].seat != null) return feed[i].seat!
  }
  return null
})

function back() {
  history.back()
}

async function exportDialog() {
  if (!store.match) return
  try {
    await api.exportDialog(store.match.id)
  } catch (e) {
    console.error('导出失败:', e)
    alert('导出失败，请重试')
  }
}
</script>

<template>
  <nav class="topbar">
    <button class="back" @click="back">← 返回</button>
    <p class="brand"><span class="logo">🐺</span><span class="word">whoisspy</span></p>
    <span v-if="store.match" class="mid-chip">#{{ store.match.id }} · {{ boardLabel(store.match.ruleset, store.match.board?.roles) }}</span>
    <button
      v-if="store.match && (store.match.status === 'running' || store.match.status === 'created')"
      class="stop-btn"
      @click="store.stop()"
    >⏹ 终止对局</button>
    <button
      v-if="store.match"
      class="export-btn"
      @click="exportDialog"
    >📥 导出对话</button>
    <button class="god-btn" :class="{ on: store.godView }" @click="store.toggleGod()">
      {{ store.godView ? '👁️ 上帝视角' : '🙈 沉浸视角' }}
    </button>
  </nav>

  <p v-if="store.loading && !store.match" class="loading">加载对局……</p>
  <main v-else-if="vm" class="stage">
    <aside class="wing">
      <SeatColumn :seats="leftSeats" side="L" :sheriff="demoState.sheriff"
                  :god-view="store.godView" :speaking-seat="speakingSeat" />
    </aside>

    <div class="center">
      <PhaseBanner :phase="demoState.phase" :day="demoState.day" :label="vm.label" />
      <section class="theater" aria-label="对局对话">
        <div class="feed">
          <template v-for="(it, i) in vm.feed" :key="i">
            <p v-if="it.kind === 'system'" class="narration">{{ it.text }}</p>
            <div v-else-if="it.kind === 'channel'" class="bubble-row channel">
              <span class="mini-avatar">{{ seats.find((s: any) => (s as any).id === it.seat)?.emoji }}</span>
              <div class="bubble ch">
                <p class="who">{{ it.seat }}号 · {{ seats.find((s: any) => (s as any).id === it.seat)?.name }} <span class="tag wolf-tag">狼队频道</span></p>
                <p class="text">{{ it.text }}</p>
              </div>
            </div>
            <div v-else-if="it.kind === 'speech' || it.kind === 'last_words'" class="bubble-row"
                 :class="seats.find((s: any) => (s as any).id === it.seat)?.side === 'R' ? 'right' : 'left'">
              <span class="mini-avatar">{{ seats.find((s: any) => (s as any).id === it.seat)?.emoji }}</span>
              <div class="bubble">
                <p class="who">{{ it.seat }}号 · {{ seats.find((s: any) => (s as any).id === it.seat)?.name }}
                  <span v-if="it.kind === 'last_words'" class="tag last-tag">遗言</span>
                </p>
                <p class="text">{{ it.text }}</p>
              </div>
            </div>
          </template>
          <p v-if="!vm.feed.length" class="narration">等待事件……</p>
        </div>
      </section>
      <VoteDrawer :vote="demoState.vote" :seats="seats" />
      <p v-if="store.usage" class="usage-line">
        用量：{{ store.usage.total_calls }} 次调用 · {{ store.usage.prompt_tokens }}+{{ store.usage.completion_tokens }} tokens
      </p>
    </div>

    <aside class="wing">
      <SeatColumn :seats="rightSeats" side="R" :sheriff="demoState.sheriff"
                  :god-view="store.godView" :speaking-seat="speakingSeat" />
    </aside>
  </main>
</template>

<style scoped>
.topbar { display: flex; align-items: center; gap: 14px; padding: 10px 18px; }
.back { padding: 7px 14px; font-size: 13px; font-weight: 900; background: var(--paper); border: var(--border-w) solid var(--ink); border-radius: 999px; box-shadow: var(--shadow-pop-sm); }
.brand { display: flex; align-items: center; gap: 8px; font-family: var(--font-display); font-size: 20px; color: var(--ink); text-shadow: 0 2px 0 rgba(255,255,255,.55); }
.logo { font-size: 22px; filter: drop-shadow(0 2px 0 var(--ink)); }
.mid-chip { font-size: 12px; font-weight: 700; color: #55507a; background: rgba(255,255,255,.7); border-radius: 999px; padding: 3px 10px; }
.stop-btn { margin-left: auto; padding: 7px 14px; font-size: 13px; font-weight: 900; background: #ffe9ef; color: var(--wolf); border: var(--border-w) solid var(--wolf); border-radius: 999px; box-shadow: 0 3px 0 var(--wolf); }
.stop-btn:hover { transform: translateY(-1px); }
.export-btn { padding: 7px 14px; font-size: 13px; font-weight: 900; background: #e8f4ff; color: var(--ink); border: var(--border-w) solid var(--ink); border-radius: 999px; box-shadow: var(--shadow-pop-sm); }
.export-btn:hover { transform: translateY(-1px); }
.god-btn { padding: 7px 15px; font-size: 13.5px; font-weight: 900; border: var(--border-w) solid var(--ink); border-radius: 999px; box-shadow: var(--shadow-pop-sm); background: var(--paper); }
.god-btn.on { background: var(--sheriff); }
.loading { text-align: center; padding: 60px; font-weight: 700; color: var(--ink); }
.stage { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(170px, 230px) minmax(0, 1fr) minmax(170px, 230px); gap: 16px; padding: 2px 18px 4px; max-width: 1500px; width: 100%; margin: 0 auto; }
.page { height: 100vh; display: flex; flex-direction: column; }
.wing { min-height: 0; overflow-y: auto; display: flex; flex-direction: column; justify-content: center; scrollbar-width: none; padding: 6px 0; }
.wing::-webkit-scrollbar { display: none; }
.center { min-height: 0; display: flex; flex-direction: column; gap: 10px; }
.theater { flex: 1; min-height: 0; display: flex; flex-direction: column; border: var(--border-w) solid var(--ink); border-radius: var(--radius-lg); background: var(--paper); box-shadow: var(--shadow-pop); overflow: hidden; }
.feed { flex: 1; overflow-y: auto; padding: 16px 18px 20px; display: flex; flex-direction: column; gap: 12px; scrollbar-width: thin; }
.narration { align-self: center; max-width: 92%; text-align: center; font-size: 13.5px; font-weight: 700; color: #6f6a85; padding: 6px 14px; background: var(--paper-dim); border-radius: 999px; border: 2px dashed #c9bd9a; }
.bubble-row { display: flex; gap: 9px; align-items: flex-end; }
.bubble-row.right { flex-direction: row-reverse; }
.bubble-row.right .who { justify-content: flex-end; }
.mini-avatar { flex: none; width: 38px; height: 38px; display: grid; place-items: center; font-size: 22px; background: var(--paper-dim); border: 2.5px solid var(--ink); border-radius: 50%; }
.bubble { max-width: 78%; background: #fff; border: 2.5px solid var(--ink); border-radius: 4px 16px 16px 16px; padding: 9px 13px 10px; box-shadow: 0 3px 0 var(--ink); }
.bubble-row.right .bubble { border-radius: 16px 4px 16px 16px; }
.bubble.ch { background: #ffe9ef; border-color: var(--wolf); box-shadow: 0 3px 0 var(--wolf); }
.who { font-size: 12px; font-weight: 900; color: #8a85a0; margin-bottom: 3px; display: flex; gap: 6px; align-items: center; }
.bubble.ch .who { color: var(--wolf); }
.tag { font-size: 10px; font-weight: 900; color: #fff; padding: 1px 7px; border-radius: 999px; border: 1.5px solid var(--ink); }
.last-tag { background: var(--dead); }
.wolf-tag { background: var(--wolf); }
.text { font-size: 14px; line-height: 1.62; white-space: pre-wrap; word-break: break-word; }
.usage-line { font-size: 12px; font-weight: 700; color: #55507a; text-align: center; padding-bottom: 6px; }
@media (max-width: 900px) {
  .stage { grid-template-columns: 1fr; }
  .wing { display: none; }
}
</style>
