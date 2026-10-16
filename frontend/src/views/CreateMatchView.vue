<script setup lang="ts">
// 建局页（档 1 观战）：选种子/开局暂停 → create（全 LLM 座位）→ 跳直播页
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useLiveStore } from '../stores/live'

const store = useLiveStore()
const router = useRouter()
const seed = ref('')
const paused = ref(true) // 默认开局暂停，玩家点「继续」开播
const creating = ref(false)

onMounted(() => {
  // 纯复盘环境（未连接引擎）时禁用建局
  void store.setup()
})

async function create() {
  if (creating.value) return
  creating.value = true
  try {
    const parsed = seed.value.trim() === '' ? undefined : Number(seed.value)
    const mid = await store.createMatch({
      seed: Number.isFinite(parsed) ? parsed : undefined,
      paused: paused.value,
    })
    void router.push(`/live/${mid}`)
  } catch (e) {
    alert(e instanceof Error ? e.message : String(e))
  } finally {
    creating.value = false
  }
}
</script>

<template>
  <nav class="topbar">
    <button class="back" @click="router.back()">← 返回</button>
    <p class="brand"><span class="logo">🐺</span><span class="word">whoisspy</span></p>
  </nav>

  <main class="wrap">
    <h1 class="page-title">创建对局</h1>
    <p v-if="!store.connected" class="state-line err">
      未连接对局引擎（需以 serve 模式启动 sidecar）
    </p>

    <form v-else class="card" @submit.prevent="create">
      <p class="mode">观战模式：9 个座位全部由 LLM 玩家对战，本机实时演播。</p>

      <label class="field">
        <span class="label">随机种子（可选）</span>
        <input v-model="seed" type="number" placeholder="留空 = 随机" />
        <span class="hint">同种子同结果（确定性可复现）。</span>
      </label>

      <label class="check">
        <input v-model="paused" type="checkbox" />
        <span>开局暂停，等我点「继续」再开播</span>
      </label>

      <button class="go" type="submit" :disabled="creating">
        {{ creating ? '正在建局……' : '🎬 开始观战' }}
      </button>
    </form>
  </main>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 20px;
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
  font-size: 21px;
  color: var(--ink);
  text-shadow: 0 2px 0 rgba(255, 255, 255, 0.55);
}
.logo { font-size: 24px; filter: drop-shadow(0 2px 0 var(--ink)); }
.wrap { max-width: 520px; margin: 0 auto; padding: 8px 20px 40px; }
.page-title {
  font-family: var(--font-display);
  font-weight: 400;
  font-size: 26px;
  margin-bottom: 14px;
  color: var(--ink);
  text-shadow: 0 2px 0 rgba(255, 255, 255, 0.6);
}
.state-line.err { color: var(--wolf); font-weight: 700; padding: 20px; }
.card {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 22px;
  background: var(--paper);
  border: var(--border-w) solid var(--ink);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-pop);
}
.mode {
  font-size: 13.5px;
  font-weight: 700;
  color: #55507a;
  background: rgba(255, 255, 255, 0.7);
  border: 2px dashed #c9bd9a;
  border-radius: var(--radius);
  padding: 10px 14px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.label { font-size: 13px; font-weight: 900; color: var(--ink); }
.field input {
  font-size: 15px;
  font-family: var(--font-num);
  padding: 9px 12px;
  border: var(--border-w) solid var(--ink);
  border-radius: var(--radius);
  background: #fffdf4;
  box-shadow: inset 0 2px 0 rgba(45, 42, 62, 0.08);
}
.hint { font-size: 12px; color: #8a85a0; }
.check {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
}
.check input {
  width: 18px;
  height: 18px;
  accent-color: var(--ink);
}
.go {
  padding: 12px;
  font-size: 16px;
  font-weight: 900;
  color: var(--paper);
  background: linear-gradient(180deg, var(--sheriff) 0%, #a4764a 100%);
  border: var(--border-w) solid var(--ink);
  border-radius: 999px;
  box-shadow: var(--shadow-pop-sm);
}
.go:disabled { opacity: 0.55; cursor: wait; }
</style>