<script setup lang="ts">
// 用量面板：调用数 / tokens / 费用 / 缓存命中率 / 兜底 / 规则异常
import { computed } from 'vue'
import type { DisplayUsage } from '../model/display'

const props = defineProps<{ usage: DisplayUsage }>()

const cost = computed(() =>
  props.usage.cost_micros ? `¥${(props.usage.cost_micros / 1e6).toFixed(2)}` : '¥0.00',
)
const tokens = computed(() =>
  (props.usage.prompt_tokens + props.usage.completion_tokens).toLocaleString(),
)
const cache = computed(() => `${(props.usage.cache_hit_rate * 100).toFixed(0)}%`)
</script>

<template>
  <section class="usage" aria-label="用量汇总">
    <span class="item">📞 {{ usage.calls }} 次调用</span>
    <span class="item">🧮 {{ tokens }} tokens</span>
    <span class="item">💰 {{ cost }}</span>
    <span class="item">⚡ 缓存命中 {{ cache }}</span>
    <span v-if="usage.fallbacks" class="item warn">⚠ 兜底 {{ usage.fallbacks }}</span>
    <span v-if="usage.rule_errors" class="item warn">⚠ 规则异常 {{ usage.rule_errors }}</span>
  </section>
</template>

<style scoped>
.usage {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 6px;
  padding: 2px 0 6px;
}
.item {
  font-size: 11.5px;
  font-weight: 700;
  color: #55507a;
  background: rgba(255, 255, 255, 0.72);
  border: 2px solid var(--ink);
  border-radius: 999px;
  padding: 2px 10px;
}
.item.warn {
  color: var(--wolf);
}
</style>