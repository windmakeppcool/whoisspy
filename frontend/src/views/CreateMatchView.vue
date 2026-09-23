<script setup lang="ts">
// 创建对局页：板子选择 + 每座位 persona/model（v1 简化：model 可手填或 mock）
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/client'
import { useCatalogStore } from '../stores/catalog'

const catalog = useCatalogStore()
const router = useRouter()
const boardId = ref('p6-classic')
const personaId = ref('calm-analyst')
const model = ref('mock')
const submitting = ref(false)
const error = ref('')

onMounted(() => catalog.refresh())

const seatCount = computed<number>(() => {
  const b = catalog.boards.find(x => x.id === boardId.value)
  return b ? Object.values(b.roles).reduce((a: number, c: number) => a + c, 0) : 6
})

async function submit() {
  submitting.value = true
  error.value = ''
  try {
    const seats = Array.from({ length: seatCount.value }, (_, i) => ({
      seat: i + 1,
      persona_id: personaId.value,
      model: model.value,
    }))
    const m = await api.createMatch({ game_type: 'werewolf', board: { id: boardId.value }, seats })
    router.push(`/matches/${m.id}`)
  } catch (e) {
    error.value = String(e instanceof Error ? e.message : e)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <nav class="topbar">
    <p class="brand"><span class="logo">🐺</span><span class="word">whoisspy</span></p>
  </nav>
  <main class="wrap">
    <h1 class="page-title">创建对局</h1>

    <section class="card">
      <h2 class="sec">① 选择板子</h2>
      <div class="boards">
        <button
          v-for="b in catalog.boards"
          :key="b.id"
          class="board"
          :class="{ on: boardId === b.id }"
          @click="boardId = b.id"
        >
          <span class="b-name">{{ b.id }}</span>
          <span class="b-sub">{{ b.ruleset === 'standard-12' ? '标准 12 人局' : `${Object.values(b.roles).reduce((a, c) => a + c, 0)} 人` }}</span>
          <span class="b-roles">
            <span v-for="(n, role) in b.roles" :key="role" class="role-chip">{{ role }}×{{ n }}</span>
          </span>
        </button>
      </div>
    </section>

    <section class="card">
      <h2 class="sec">② 选手人设（全部座位同款，M3 支持逐座配置）</h2>
      <div class="field">
        <label>人设</label>
        <select v-model="personaId">
          <option v-for="p in catalog.personas" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
      </div>
      <div class="field">
        <label>模型</label>
        <input v-model="model" type="text" placeholder="mock 或 OpenAI 兼容模型 id" />
      </div>
      <p class="hint">模型接入（base_url / api_key_env）暂由后端配置提供；mock 模型走剧本兜底可完整跑局。</p>
    </section>

    <p v-if="error" class="error">{{ error }}</p>
    <button class="go" :disabled="submitting" @click="submit">
      {{ submitting ? '创建中……' : `开赛！（${seatCount} 个 AI 座位）` }}
    </button>
  </main>
</template>

<style scoped>
.topbar { display: flex; align-items: center; padding: 12px 20px; }
.brand { display: flex; align-items: center; gap: 8px; font-family: var(--font-display); font-size: 21px; color: var(--ink); text-shadow: 0 2px 0 rgba(255,255,255,.55); }
.logo { font-size: 24px; filter: drop-shadow(0 2px 0 var(--ink)); }
.wrap { max-width: 720px; margin: 0 auto; padding: 8px 20px 40px; display: flex; flex-direction: column; gap: 14px; }
.page-title { font-family: var(--font-display); font-weight: 400; font-size: 26px; color: var(--ink); text-shadow: 0 2px 0 rgba(255,255,255,.6); }
.card { background: var(--paper); border: var(--border-w) solid var(--ink); border-radius: var(--radius-lg); box-shadow: var(--shadow-pop-sm); padding: 16px 18px; }
.sec { font-size: 15px; font-weight: 900; margin-bottom: 12px; }
.boards { display: flex; flex-wrap: wrap; gap: 10px; }
.board { flex: 1 1 150px; padding: 11px 13px; background: #fff; border: 2.5px solid var(--ink); border-radius: var(--radius); text-align: left; display: flex; flex-direction: column; gap: 5px; }
.board.on { background: #e8f4ff; box-shadow: 0 3px 0 var(--ink); }
.b-name { font-weight: 900; font-size: 14px; }
.b-sub { font-size: 11.5px; color: #8a85a0; }
.b-roles { display: flex; flex-wrap: wrap; gap: 4px; }
.role-chip { font-size: 10px; font-weight: 700; background: var(--paper-dim); border: 1.5px solid var(--ink); border-radius: 6px; padding: 0 5px; }
.field { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.field label { flex: none; width: 52px; font-weight: 900; font-size: 13px; }
.field select, .field input { flex: 1; padding: 8px 11px; font-size: 13.5px; border: 2.5px solid var(--ink); border-radius: 9px; background: #fff; font-family: inherit; }
.hint { font-size: 12px; color: #8a85a0; }
.error { padding: 10px 14px; background: #ffe9ef; border: 2.5px solid var(--wolf); border-radius: var(--radius); font-weight: 700; font-size: 13px; color: var(--wolf); }
.go { align-self: flex-start; padding: 11px 26px; font-size: 15px; font-weight: 900; background: var(--witch); color: #fff; border: var(--border-w) solid var(--ink); border-radius: 999px; box-shadow: var(--shadow-pop-sm); }
.go:hover { transform: translateY(-1px); }
.go:disabled { opacity: .6; }
</style>
