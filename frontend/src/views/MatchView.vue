<script setup lang="ts">
// 复盘舞台：展示文档 → 组件（纯渲染；视角切换 = 换文档重拉）
import { computed, inject, onMounted, ref, watch, type Ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DialogueTheater from '../components/DialogueTheater.vue'
import DirectorBar from '../components/DirectorBar.vue'
import PhaseBanner from '../components/PhaseBanner.vue'
import SeatColumn from '../components/SeatColumn.vue'
import UsagePanel from '../components/UsagePanel.vue'
import VoteDrawer from '../components/VoteDrawer.vue'
import { boardLabel } from '../model/types'
import { buildSeats, lastVoteRound, speakingSeat } from '../model/replay'
import type { View } from '../model/display'
import { useReplayStore } from '../stores/replay'

const route = useRoute()
const router = useRouter()
const store = useReplayStore()
const theater = ref<InstanceType<typeof DialogueTheater> | null>(null)
const globalPhase = inject<Ref<'night' | 'day'>>('globalPhase')

const isLocal = computed(() => route.params.id === 'local')
const routeView = computed<View>(() =>
  route.query.view === 'public' ? 'public' : 'god',
)

onMounted(() => {
  if (isLocal.value) {
    if (!store.doc) void router.replace('/') // 无本地文档（刷新/直达）回列表
  } else {
    void store.load(route.params.id as string, routeView.value)
  }
})
watch(
  () => route.params.id,
  (id) => {
    if (id && !isLocal.value) void store.load(id as string, routeView.value)
  },
)

// 当前段驱动：座位列/木牌/投票抽屉/天空全部取该段 stage/votes（段快照 → 任意前缀渲染零成本）
// 注：Pinia 对 store 上的 ref/computed 自动解包，访问时不再写 .value
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
const resultBanner = computed(() => {
  const d = store.doc
  if (!d || d.match.status !== 'finished' || !d.match.winner) return null
  // 保留悬念：进度推进到终章才揭示胜负（剧场尾行的对局结束本就只在末段存在）
  if (store.currentSegment !== store.segments.length - 1) return null
  const camp = d.match.winner === 'wolf' ? '狼人阵营' : '好人阵营'
  return `🏁 ${camp}获胜（${d.match.reason}）`
})

watch(
  () => store.current?.is_night,
  (night) => {
    if (globalPhase) globalPhase.value = night ? 'night' : 'day'
  },
)

function onSegmentChange(index: number) {
  store.seek(index)
}
function step(dir: 1 | -1) {
  const next = store.currentSegment + dir
  if (next >= 0 && next < store.segments.length) {
    store.seek(next)
    theater.value?.scrollToSegment(next)
  }
}
function seek(index: number) {
  store.seek(index)
  theater.value?.scrollToSegment(index)
}
</script>

<template>
  <div class="page">
    <nav class="topbar">
      <button class="back" @click="router.back()">← 返回</button>
      <p class="brand"><span class="logo">🐺</span><span class="word">whoisspy</span></p>
      <span v-if="store.doc" class="mid-chip">{{ chip }}</span>
      <span v-if="store.localMode" class="mid-chip local">📄 本地文件</span>
      <span class="spacer"></span>
      <button
        class="god-btn"
        :class="{ on: store.godView }"
        :disabled="store.localMode"
        :title="store.localMode ? '本地文件是单视角文档' : '切换视角（G）'"
        @click="store.setView(store.godView ? 'public' : 'god')"
      >
        {{ store.godView ? '👁️ 上帝视角' : '🙈 沉浸视角' }}
      </button>
    </nav>

    <div v-if="store.loading" class="loading-wrap">
      <div class="loading-spinner" aria-hidden="true"></div>
      <p class="state-line">正在加载对局……</p>
    </div>
    <p v-else-if="store.error" class="state-line err">{{ store.error }}</p>

    <main v-else-if="store.doc" class="stage">
      <aside class="wing">
        <SeatColumn
          :seats="leftSeats"
          side="L"
          :sheriff="store.current?.stage.sheriff ?? null"
          :god-view="store.godView"
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
          @segment-change="onSegmentChange"
        />
        <VoteDrawer :vote="vote" :seats="seats" />
        <UsagePanel v-if="store.doc" :usage="store.doc.usage" />
      </div>

      <aside class="wing">
        <SeatColumn
          :seats="rightSeats"
          side="R"
          :sheriff="store.current?.stage.sheriff ?? null"
          :god-view="store.godView"
          :speaking-seat="speaking"
        />
      </aside>
    </main>

    <DirectorBar
      v-if="store.doc && !store.loading"
      :chapter-index="store.currentSegment"
      :chapter-labels="store.segmentLabels"
      @step="step"
      @seek="seek"
    />
  </div>
</template>

<style scoped>
/* 复盘页自约束为视口高度（页面不滚，剧场内滚，见 frontend-design 布局） */
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
.mid-chip.local { background: #e8f4ff; }
.spacer { flex: 1; }
.god-btn {
  padding: 7px 15px;
  font-size: 13.5px;
  font-weight: 900;
  border: var(--border-w) solid var(--ink);
  border-radius: 999px;
  box-shadow: var(--shadow-pop-sm);
  background: var(--paper);
}
.god-btn.on { background: var(--sheriff); }
.god-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.state-line {
  text-align: center;
  padding: 60px;
  font-weight: 700;
  color: var(--ink);
}
.state-line.err { color: var(--wolf); }

/* 加载占位：旋转圈 + 文案，垂直居中占据舞台区（避免视角切换时旧内容闪现） */
.loading-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 18px;
}
.loading-wrap .state-line { padding: 0; }
.loading-spinner {
  width: 44px;
  height: 44px;
  border: 5px solid var(--paper-dim);
  border-top-color: var(--ink);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

.stage {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(170px, 230px) minmax(0, 1fr) minmax(170px, 230px);
  grid-template-rows: minmax(0, 1fr); /* 行高锁定视口内，避免座位列内容撑破网格 */
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