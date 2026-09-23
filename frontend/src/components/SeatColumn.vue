<script setup lang="ts">
// 座位列：一列座位卡（左右两侧各半场）
import type { Seat } from '../model/types'
import SeatCard from './SeatCard.vue'

defineProps<{
  seats: Seat[]
  side: 'L' | 'R'
  sheriff: number | null
  godView: boolean
  speakingSeat: number | null
}>()
</script>

<template>
  <div class="seat-col" :class="side" role="list" aria-label="座位">
    <SeatCard
      v-for="seat in seats"
      :key="seat.id"
      role="listitem"
      :seat="seat"
      :sheriff="sheriff === seat.id"
      :god-view="godView"
      :is-speaking="speakingSeat === seat.id"
    />
  </div>
</template>

<style scoped>
.seat-col {
  display: flex;
  flex-direction: column;
  gap: 10px;
  justify-content: center;
  min-width: 0;
}
.seat-col.R {
  align-items: stretch;
}
@media (max-width: 900px) {
  .seat-col {
    flex-direction: row;
    flex-wrap: wrap;
  }
  .seat-col.L {
    justify-content: flex-start;
  }
  .seat-col.R {
    justify-content: flex-end;
  }
  .seat-col :deep(.seat-card) {
    flex: 1 1 46%;
    min-width: 150px;
  }
}
</style>
