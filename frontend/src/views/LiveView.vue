<script setup lang="ts">
// 直播页（档 1 观战闭环）：ApiSource 帧流 → 复盘舞台实时演播；
// 观赛/复盘共用组件（frontend.md 八），仅数据驱动方式不同。
import { computed, inject, onMounted, ref, watch, type Ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DialogueTheater from '../components/DialogueTheater.vue'
import DirectorBar from '../components/DirectorBar.vue'
import PaceBar from '../components/PaceBar.vue'
import PhaseBanner from '../components/PhaseBanner.vue'
import SeatColumn from '../components/SeatColumn.vue'
import UsagePanel from '../components/UsagePanel.vue'
import VoteDrawer from '../components/VoteDrawer.vue'
import { boardLabel } from '../model/types'
import { buildSeats, lastVoteRound, speakingSeat } from '../model/replay'
import { useLiveStore } from '../stores/live'

const route = useRoute()
const router = useRouter()
const store = useLiveStore()
const theater = ref<InstanceType<typeof DialogueTheater> | null>(null)
const globalPhase = inject<Ref<'night' | 'day'>>('globalPhase')

onMounted(async () => {
  const ok = await store.setup()
  if (!ok) {
    // 未连接引擎（纯复盘环境）：无对局可看
    return
  }
  if (!store.doc) {
    // 直接打开直播页且尚无对局 → 回列表引导建局
    void router.replace('/')
  }
})

// 当前段驱动（与复盘页同构：段快照 → 任意前缀渲染零成本）
const seats = computed(() =>
  store.current ? buildSeats(store.doc!, store.current.stage) : [],
)
const leftSeats = computed(() => seats.value.filter((s) => s.side === 'L'))
const rightSeats = computed(() => seats.value.filter((s) => s.side === 'R'))
const vote = computed(() => (store.current ? lastVoteRound(store.current) : null))
const speaking = computed(() => (store.current ? speakingSeat(store.current) : null))
const chip = computed(() =>
  store.doc
    ? `#${store.doc.match_id} · ${boardLabel('standard-9', store.doc.match.board.roles)}`
    : '',
)
const live = computed(() => !!store.doc && store.doc.match.status === 'running')
const resultBanner = computed(() => {
  const d = store.doc
  if (!d) return null
  if (d.match.status === 'finished' && d.match.winner) {
    const camp = d.match.winner === 'wolf' ? '狼人阵营' : '好人阵营'
    return `🏁 ${camp}获胜（${d.match.reason}）`
  }
  if (d.match.status === 'stopped') return `⏹ 对局终止（${d.match.reason}）`
  return null
})

watch(
  () => store.current?.is_night,
  (night) => {
    if (globalPhase) globalPhase.value = night ? 'night' : 'day'
  },
)

// 直播：段落导航禁用（当前段自动跟随最新段）
function togglePace() {
  if (store.paused) void store.pace('resume')
  else void store.pace('pause')
}
function frame() {
  void store.pace('frame')
}
function speed(value: number) {
  void store.pace('speed', value)
}
</script>

<template>
  <div class="page">
    <nav class="topbar">
      <button class="back" @click="router.push('/')">← 列表</button>
      <p class="brand"><span class="logo">🐺</span><span class="word">whoisspy</span></p>
      <span v-if="store.doc" class="mid-chip">{{ chip }}</span>
      <span v-if="live" class="live-dot">● 直播中</span>
      <span v-else-if="store.finished" class="live-dot done">🏁 已结束</span>
      <span v-else-if="store.stopped" class="live-dot stop">⏹ 已终止</span>
      <span class="spacer"></span>
      <PaceBar
        :paused="store.paused"
        :disabled="!store.doc || !live"
        @toggle="togglePace"
        @frame="frame"
        @speed="speed"
      />
    </nav>

    <p v-if="store.error" class="state-line err">{{ store.error }}</p>
    <div v-else-if="!store.doc" class="state-line">
      正在等待对局开始……（无对局时请从列表页创建）
    </div>

    <main v-else class="stage">
      <aside class="wing">
        <SeatColumn
          :seats="leftSeats"
          side="L"
          :sheriff="store.current?.stage.sheriff ?? null"
          :god-view="true"
          :speaking-seat="speaking"
        />
      </aside>

      <div class="center">
        <PhaseBanner
          v-if="store.current"
          :phase="store.current.is_night ? 'night' : 'day'"
          :day="store.current.day_index"
          :label="store.current.label"
          :show-day="store.current.day_index > 0"
        />
        <p v-if="resultBanner" class="result-banner">{{ resultBanner }}</p>
        <DialogueTheater
          ref="theater"
          :segments="store.segments"
          :seats="seats"
        />
        <VoteDrawer :vote="vote" :seats="seats" />
        <UsagePanel v-if="store.doc" :usage="store.doc.usage" />
      </div>

      <aside class="wing">
        <SeatColumn
          :seats="rightSeats"
          side="R"
          :sheriff="store.current?.stage.sheriff ?? null"
          :god-view="true"
          :speaking-seat="speaking"
        />
      </aside>
    </main>

    <DirectorBar
      v-if="store.doc"
      :chapter-index="store.currentSegment"
      :chapter-labels="store.segmentLabels"
      @step="() => {}"
      @seek="() => {}"
    />
  </div>
</template>

<style scoped>
/* 与复盘页同布局：视口锁定、剧场内滚（frontend-design） */
.page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.topbar {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 18px;
}
.back {
  padding: 7px 14px;
  font-size: 13px;
  font-weight: 900;
  background: var(--paper);
  border: var(--border-w) solid var(--ink);
  border-radius: 999px;
  box-shadow: var(--shadow-pop-sm);
}
.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: var(--font-display);
  font-size: 20px;
  color: var(--ink);
  text-shadow: 0 2px 0 rgba(255, 255, 255, 0.55);
}
.logo { font-size: 22px; filter: drop-shadow(0 2px 0 var(--ink)); }
.mid-chip {
  font-size: 12px;
  font-weight: 700;
  color: #55507a;
  background: rgba(255, 255, 255, 0.7);
  border-radius: 999px;
  padding: 3px 10px;
}
.live-dot {
  font-size: 11px;
  font-weight: 900;
  color: #fff;
  background: var(--wolf);
  border: 2px solid var(--ink);
  border-radius: 999px;
  padding: 2px 9px;
  animation: pulse 1.6s ease-in-out infinite;
}
.live-dot.done { background: #4a8a3a; animation: none; }
.live-dot.stop { background: #7d7894; animation: none; }
@keyframes pulse {
  50% { opacity: 0.55; }
}
.spacer { flex: 1; }
.state-line {
  text-align: center;
  padding: 60px;
  font-weight: 700;
  color: var(--ink);
}
.state-line.err { color: var(--wolf); }
.stage {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(170px, 230px) minmax(0, 1fr) minmax(170px, 230px);
  grid-template-rows: minmax(0, 1fr);
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
.wing::-webkit-scrollbar { display: none; }
.center {
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.result-banner {
  text-align: center;
  font-size: 14px;
  font-weight: 900;
  color: var(--paper);
  background: linear-gradient(180deg, #b98a5a 0%, #a4764a 100%);
  border: var(--border-w) solid var(--ink);
  border-radius: 999px;
  box-shadow: var(--shadow-pop-sm);
  padding: 6px 14px;
  margin: 0 auto;
}
@media (max-width: 900px) {
  .stage {
    grid-template-columns: 1fr;
  }
  .wing { display: none; }
}
</style>