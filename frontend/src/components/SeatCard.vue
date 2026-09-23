<script setup lang="ts">
// 座位卡：贴纸头像 + 角色徽章（上帝视角）+ 存活状态
import { computed } from 'vue'
import type { Seat } from '../model/types'
import { ROLE_NAMES } from '../model/types'

const props = defineProps<{
  seat: Seat
  sheriff: boolean
  godView: boolean
  isSpeaking: boolean
}>()

const teamClass = computed(() => (props.seat.team === 'wolf' ? 'wolf' : 'good'))
</script>

<template>
  <article
    class="seat-card"
    :class="[teamClass, { dead: !seat.alive, speaking: isSpeaking, sheriff, god: godView }]"
    :aria-label="`${seat.id}号 ${seat.name}`"
  >
    <span v-if="sheriff" class="badge-sheriff" title="警长">🏅</span>
    <div class="avatar">
      <span class="face">{{ seat.emoji }}</span>
      <span v-if="!seat.alive" class="grave" aria-hidden="true">✖</span>
    </div>
    <div class="meta">
      <p class="no">{{ seat.id }} 号</p>
      <p class="name">{{ seat.name }}</p>
      <p class="model">{{ seat.model }}</p>
    </div>
    <div v-if="godView" class="role-chip" :class="teamClass">
      {{ ROLE_NAMES[seat.role] }}
    </div>
    <span v-if="isSpeaking" class="speak-dot" aria-hidden="true"></span>
  </article>
</template>

<style scoped>
.seat-card {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 11px;
  background: var(--paper);
  border: var(--border-w) solid var(--ink);
  border-radius: var(--radius);
  box-shadow: var(--shadow-pop-sm);
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}
.seat-card:hover {
  transform: translateY(-2px);
}

/* 说话中的座位弹起来 + 描边高亮 */
.seat-card.speaking {
  transform: translateY(-3px) scale(1.03);
  box-shadow: 0 6px 0 var(--ink);
}

/* 阵营色左边条——仅上帝视角透出（沉浸视角保持中性，防阵营泄漏） */
.seat-card::before {
  content: '';
  position: absolute;
  left: -3px;
  top: 8px;
  bottom: 8px;
  width: 6px;
  border-radius: 4px;
  background: var(--paper-dim);
}
.seat-card.god.wolf::before { background: var(--wolf); }
.seat-card.god.good::before { background: var(--good); }

.seat-card.dead {
  opacity: 0.62;
  filter: grayscale(0.75);
}
.seat-card.dead .name {
  text-decoration: line-through;
}

.avatar {
  position: relative;
  flex: none;
  width: 46px;
  height: 46px;
  display: grid;
  place-items: center;
  background: var(--paper-dim);
  border: 2.5px solid var(--ink);
  border-radius: 50%;
  font-size: 26px;
}
.grave {
  position: absolute;
  inset: -6px;
  display: grid;
  place-items: center;
  font-size: 30px;
  font-weight: 900;
  color: var(--wolf);
  text-shadow: 0 0 4px var(--paper);
  transform: rotate(-8deg);
}

.meta {
  min-width: 0;
  flex: 1;
}
.no {
  font-family: var(--font-num);
  font-weight: 800;
  font-size: 12px;
  letter-spacing: 0.04em;
  color: #8a85a0;
  line-height: 1.15;
}
.name {
  font-weight: 900;
  font-size: 14.5px;
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.model {
  font-size: 11px;
  font-weight: 500;
  color: #8a85a0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.role-chip {
  position: absolute;
  right: -8px;
  top: -10px;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 900;
  color: #fff;
  border: 2px solid var(--ink);
  border-radius: 999px;
  box-shadow: 0 2px 0 var(--ink);
  transform: rotate(4deg);
}
.role-chip.wolf { background: var(--wolf); }
.role-chip.good { background: var(--good); }
.role-chip.seer { background: var(--seer); }
.role-chip.witch { background: var(--witch); }

.badge-sheriff {
  position: absolute;
  left: -12px;
  top: -14px;
  font-size: 24px;
  transform: rotate(-14deg);
  filter: drop-shadow(0 2px 0 var(--ink));
  z-index: 1;
}

/* 说话气泡点 */
.speak-dot {
  position: absolute;
  right: 10px;
  bottom: 8px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--seer);
  border: 2px solid var(--ink);
  animation: pop 0.9s ease infinite;
}
@keyframes pop {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.45); }
}
</style>
