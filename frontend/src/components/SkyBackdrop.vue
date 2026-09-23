<script setup lang="ts">
// 签名元素：昼夜天空场景层——太阳/月亮/星空/村庄剪影随游戏阶段联动
import { computed } from 'vue'

const props = defineProps<{ phase: 'night' | 'day' }>()

const stars = Array.from({ length: 34 }, (_, i) => ({
  left: (i * 61.8) % 100,
  top: (i * 37.7) % 55,
  size: 1.5 + ((i * 13) % 5) * 0.55,
  delay: (i % 7) * 0.4,
  bright: i % 9 === 0,
}))
</script>

<template>
  <div class="sky" :class="props.phase" aria-hidden="true">
    <div class="celestial" :class="props.phase"></div>
    <div class="stars">
      <span
        v-for="(st, i) in stars"
        :key="i"
        class="star"
        :class="{ bright: st.bright }"
        :style="{ left: st.left + '%', top: st.top + '%', width: st.size + 'px', height: st.size + 'px', animationDelay: st.delay + 's' }"
      ></span>
    </div>
    <svg class="village" viewBox="0 0 1200 190" preserveAspectRatio="none">
      <!-- 远山 -->
      <path
        class="v-hills"
        d="M0,190 L0,120 Q150,60 300,110 T600,100 T900,115 T1200,90 L1200,190 Z"
      />
      <!-- 村庄剪影：房子与树 -->
      <g class="v-houses">
        <path d="M80,190 L80,140 L105,118 L130,140 L130,190 Z" />
        <path d="M170,190 L170,150 L190,132 L210,150 L210,190 Z" />
        <rect x="258" y="128" width="26" height="62" />
        <path d="M252,130 L271,112 L290,130 Z" />
        <path d="M560,190 L560,146 L585,124 L610,146 L610,190 Z" />
        <path d="M650,190 L650,158 L668,142 L686,158 L686,190 Z" />
        <rect x="742" y="140" width="24" height="50" />
        <path d="M736,142 L754,124 L772,142 Z" />
        <path d="M1030,190 L1030,142 L1056,120 L1082,142 L1082,190 Z" />
        <path d="M1120,190 L1120,156 L1138,140 L1156,156 L1156,190 Z" />
        <!-- 风车 -->
        <rect x="880" y="126" width="14" height="64" />
        <g class="mill" transform="translate(887,122)">
          <path d="M0,0 L26,7 L0,14 Z" />
          <path d="M0,0 L-26,-7 L0,-14 Z" />
          <path d="M0,0 L-7,-26 L-14,0 Z" />
          <path d="M0,0 L7,26 L14,0 Z" />
        </g>
      </g>
    </svg>
  </div>
</template>

<style scoped>
.sky {
  position: fixed;
  inset: 0;
  z-index: -1;
  overflow: hidden;
  transition: background 2.4s ease;
}
.sky.day {
  background: linear-gradient(180deg, var(--sky-day-top) 0%, var(--sky-day-bottom) 78%);
}
.sky.night {
  background: linear-gradient(180deg, var(--sky-night-top) 0%, var(--sky-night-bottom) 78%);
}

/* 太阳/月亮同一颗天体，随昼夜升降变色 */
.celestial {
  position: absolute;
  top: 7%;
  right: 11%;
  width: 92px;
  height: 92px;
  border-radius: 50%;
  transition: all 2.4s ease;
}
.celestial.day {
  background: var(--sun);
  box-shadow:
    0 0 0 10px rgba(255, 215, 94, 0.35),
    0 0 0 22px rgba(255, 215, 94, 0.14);
  top: 13%;
  right: 13%;
}
.celestial.night {
  background: var(--moon);
  box-shadow: 0 0 0 8px rgba(245, 233, 96, 0.18);
  top: 10%;
  right: 15%;
  /* 月牙：叠一个背景色圆 */
  overflow: hidden;
}
.celestial.night::after {
  content: '';
  position: absolute;
  left: -34%;
  top: -14%;
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: var(--sky-night-top);
}

.stars {
  position: absolute;
  inset: 0;
  opacity: 0;
  transition: opacity 2.4s ease;
}
.sky.night .stars {
  opacity: 1;
}
.star {
  position: absolute;
  border-radius: 50%;
  background: #fdf6c9;
  animation: twinkle 3.2s ease-in-out infinite;
}
.star.bright {
  box-shadow: 0 0 6px 1px rgba(253, 246, 201, 0.8);
}
@keyframes twinkle {
  0%, 100% { opacity: 0.35; }
  50% { opacity: 1; }
}

.village {
  position: absolute;
  bottom: 0;
  left: 0;
  width: 100%;
  height: clamp(110px, 17vh, 190px);
}
.v-hills {
  fill: var(--grass-day);
  transition: fill 2.4s ease;
}
.sky.night .v-hills {
  fill: var(--grass-night);
}
.v-houses {
  fill: var(--village-day);
  transition: fill 2.4s ease;
}
.sky.night .v-houses {
  fill: var(--village-night);
}
.mill {
  animation: mill-spin 9s linear infinite;
  transform-origin: 0 0;
}
@keyframes mill-spin {
  to { transform: rotate(360deg); }
}
</style>
