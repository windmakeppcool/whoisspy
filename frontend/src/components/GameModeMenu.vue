<script setup lang="ts">
// 顶部栏：品牌 + 游戏模式菜单（含锁定项）+ 视角开关
import { ref } from 'vue'
import { MATCHES, LOCKED_GAMES } from '../mock/match'

defineProps<{ currentMode: string; godView: boolean }>()
const emit = defineEmits<{ (e: 'select', mode: string): void; (e: 'toggle-god'): void }>()

const open = ref(false)

function pick(mode: string) {
  open.value = false
  emit('select', mode)
}
</script>

<template>
  <nav class="topbar">
    <p class="brand">
      <span class="logo">🐺</span>
      <span class="word">whoisspy</span>
    </p>

    <div class="mode-wrap">
      <button
        class="mode-btn"
        :aria-expanded="open"
        @click="open = !open"
      >
        🎮 游戏模式
        <span class="caret" :class="{ up: open }">▾</span>
      </button>
      <ul v-if="open" class="menu">
        <li v-for="m in MATCHES" :key="m.mode">
          <button class="item" :class="{ active: m.mode === currentMode }" @click="pick(m.mode)">
            {{ m.name }}
            <span v-if="m.mode === currentMode" class="check">✓</span>
          </button>
        </li>
        <li v-for="g in LOCKED_GAMES" :key="g.name">
          <button class="item locked" disabled>
            {{ g.name }}
            <span class="hint">{{ g.hint }}</span>
          </button>
        </li>
      </ul>
    </div>

    <button class="god-btn" :class="{ on: godView }" @click="emit('toggle-god')">
      {{ godView ? '👁️ 上帝视角' : '🙈 沉浸视角' }}
    </button>
  </nav>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 18px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: var(--font-display);
  font-size: 21px;
  color: var(--ink);
  text-shadow: 0 2px 0 rgba(255, 255, 255, 0.55);
}
.logo {
  font-size: 24px;
  filter: drop-shadow(0 2px 0 var(--ink));
}
.mode-wrap {
  position: relative;
}
.mode-btn {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 15px;
  font-size: 14px;
  font-weight: 900;
  background: var(--paper);
  border: var(--border-w) solid var(--ink);
  border-radius: 999px;
  box-shadow: var(--shadow-pop-sm);
  transition: transform 0.15s ease;
}
.mode-btn:hover {
  transform: translateY(-1px);
}
.caret {
  font-size: 11px;
  transition: transform 0.2s ease;
}
.caret.up {
  transform: rotate(180deg);
}
.menu {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  z-index: 30;
  min-width: 230px;
  list-style: none;
  background: var(--paper);
  border: var(--border-w) solid var(--ink);
  border-radius: var(--radius);
  box-shadow: var(--shadow-pop);
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.item {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 11px;
  font-size: 13.5px;
  font-weight: 700;
  border-radius: 9px;
  text-align: left;
}
.item:hover {
  background: var(--paper-dim);
}
.item.active {
  background: #e8f4ff;
}
.check {
  color: var(--seer);
  font-weight: 900;
}
.item.locked {
  opacity: 0.5;
  cursor: not-allowed;
}
.hint {
  font-size: 10.5px;
  font-weight: 500;
  color: #8a85a0;
}
.god-btn {
  margin-left: auto;
  padding: 7px 15px;
  font-size: 13.5px;
  font-weight: 900;
  border: var(--border-w) solid var(--ink);
  border-radius: 999px;
  box-shadow: var(--shadow-pop-sm);
  background: var(--paper);
  transition: all 0.15s ease;
}
.god-btn.on {
  background: var(--sheriff);
}
</style>
