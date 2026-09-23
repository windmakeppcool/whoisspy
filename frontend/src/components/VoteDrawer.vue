<script setup lang="ts">
// 投票抽屉：票数条形榜 + 出局标记
import { computed } from 'vue'
import type { Seat, VoteRound } from '../model/types'

const props = defineProps<{
  vote: VoteRound | null
  seats: Seat[]
}>()

const rows = computed(() => {
  if (!props.vote) return []
  const byId = new Map(props.seats.map((s) => [s.id, s]))
  const entries = Object.entries(props.vote.tally).map(([id, n]) => ({
    id: Number(id),
    n,
    seat: byId.get(Number(id)),
  }))
  const max = Math.max(...entries.map((e) => e.n), 1)
  return entries.sort((a, b) => b.n - a.n).map((e) => ({ ...e, pct: (e.n / max) * 100 }))
})
</script>

<template>
  <section v-if="vote" class="drawer" aria-label="投票结果">
    <h2 class="title">🗳️ {{ vote.title }}</h2>
    <ul class="bars">
      <li v-for="row in rows" :key="row.id" class="bar-row">
        <span class="who">{{ row.seat?.emoji }} {{ row.id }}号 {{ row.seat?.name }}</span>
        <span class="track">
          <span class="fill" :style="{ width: row.pct + '%' }"></span>
        </span>
        <span class="num">{{ row.n }}</span>
        <span v-if="vote.exile === row.id" class="out">出局</span>
      </li>
    </ul>
    <p v-if="vote.exile === undefined" class="result peaceful">🕊️ 平票 —— 平安日，无人出局</p>
    <p v-else class="result">⚖️ {{ vote?.exile }}号「{{ seats.find((s) => s.id === vote?.exile)?.name }}」被放逐出局</p>
  </section>
</template>

<style scoped>
.drawer {
  border: var(--border-w) solid var(--ink);
  border-radius: var(--radius);
  background: var(--paper);
  box-shadow: var(--shadow-pop-sm);
  padding: 12px 16px 13px;
  display: flex;
  flex-direction: column;
  gap: 9px;
}
.title {
  font-family: var(--font-display);
  font-weight: 400;
  font-size: 15.5px;
  letter-spacing: 0.05em;
}
.bars {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.bar-row {
  display: grid;
  grid-template-columns: 110px 1fr 26px auto;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
}
.who {
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.track {
  height: 14px;
  background: var(--paper-dim);
  border: 2px solid var(--ink);
  border-radius: 999px;
  overflow: hidden;
}
.fill {
  display: block;
  height: 100%;
  background: var(--good);
  border-right: 2px solid var(--ink);
  transition: width 0.5s ease;
}
.num {
  font-family: var(--font-num);
  font-weight: 800;
  text-align: center;
}
.out {
  font-size: 10.5px;
  font-weight: 900;
  color: #fff;
  background: var(--wolf);
  border: 1.5px solid var(--ink);
  border-radius: 999px;
  padding: 0 7px;
}
.result {
  font-size: 13px;
  font-weight: 900;
  color: var(--wolf);
}
.result.peaceful {
  color: #5a8a4a;
}
</style>
