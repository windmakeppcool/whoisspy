<script setup lang="ts">
// 阶段横幅：木牌样式，标明当前阶段与天数
defineProps<{ phase: 'night' | 'day'; day: number; label: string }>()
</script>

<template>
  <header class="banner" :class="phase">
    <span class="icon">{{ phase === 'night' ? '🌙' : '☀️' }}</span>
    <h1 class="title">{{ label }}</h1>
    <span class="day-chip">
      <span class="day-label">第</span>
      <span class="day-num">{{ day }}</span>
      <span class="day-label">{{ phase === 'night' ? '夜' : '天' }}</span>
    </span>
  </header>
</template>

<style scoped>
.banner {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 9px 18px;
  background: linear-gradient(180deg, #b98a5a 0%, #a4764a 100%);
  border: var(--border-w) solid var(--ink);
  border-radius: var(--radius);
  box-shadow: var(--shadow-pop);
  color: var(--paper);
  position: relative;
}
/* 木纹两颗铆钉 */
.banner::before,
.banner::after {
  content: '';
  position: absolute;
  top: 50%;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ink);
  transform: translateY(-50%);
}
.banner::before { left: 12px; }
.banner::after { right: 12px; }

.icon {
  font-size: 22px;
  transform: translateY(-1px);
}
.title {
  font-family: var(--font-display);
  font-weight: 400;
  font-size: 19px;
  letter-spacing: 0.06em;
  text-shadow: 0 2px 0 rgba(45, 42, 62, 0.55);
}
.day-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 3px;
  padding: 2px 10px;
  background: var(--paper);
  color: var(--ink);
  border: 2px solid var(--ink);
  border-radius: 999px;
  box-shadow: 0 2px 0 var(--ink);
}
.day-label {
  font-size: 11px;
  font-weight: 700;
}
.day-num {
  font-family: var(--font-num);
  font-size: 17px;
  font-weight: 800;
  line-height: 1;
}
</style>
