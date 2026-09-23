<script setup lang="ts">
// 对局列表页
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMatchListStore } from '../stores/matchList'
import { boardLabel } from '../model/types'

const store = useMatchListStore()
const router = useRouter()

onMounted(() => store.refresh())

const statusLabel: Record<string, string> = {
  created: '准备中', running: '进行中', finished: '已结束', stopped: '已终止',
}

function open(id: number) {
  router.push(`/matches/${id}`)
}

async function create() {
  router.push('/create')
}
</script>

<template>
  <nav class="topbar">
    <p class="brand"><span class="logo">🐺</span><span class="word">whoisspy</span></p>
    <button class="new-btn" @click="create">＋ 创建对局</button>
  </nav>

  <main class="wrap">
    <h1 class="page-title">对局列表</h1>
    <p v-if="store.loading" class="empty">加载中……</p>
    <p v-else-if="!store.matches.length" class="empty">
      还没有对局。点击「创建对局」开一场 AI 狼人杀。
    </p>
    <ul v-else class="list">
      <li v-for="m in store.matches" :key="m.id">
        <button class="row" @click="open(m.id)">
          <span class="id-chip">#{{ m.id }}</span>
          <span class="info">
            <span class="title">狼人杀 · {{ boardLabel(m.ruleset, m.board?.roles) }}</span>
            <span class="sub">{{ m.seats.length }} 座位 · 种子 {{ m.rng_seed }}</span>
          </span>
          <span class="status" :class="m.status">{{ statusLabel[m.status] ?? m.status }}</span>
          <span v-if="m.result" class="result" :class="m.result.winner">
            {{ m.result.winner === 'wolf' ? '🐺 狼胜' : '👍 好人胜' }}
          </span>
        </button>
      </li>
    </ul>
  </main>
</template>

<style scoped>
.topbar { display: flex; align-items: center; gap: 14px; padding: 12px 20px; }
.brand { display: flex; align-items: center; gap: 8px; font-family: var(--font-display); font-size: 21px; color: var(--ink); text-shadow: 0 2px 0 rgba(255,255,255,.55); }
.logo { font-size: 24px; filter: drop-shadow(0 2px 0 var(--ink)); }
.new-btn { margin-left: auto; padding: 8px 16px; font-size: 14px; font-weight: 900; background: var(--paper); border: var(--border-w) solid var(--ink); border-radius: 999px; box-shadow: var(--shadow-pop-sm); }
.new-btn:hover { transform: translateY(-1px); }
.wrap { max-width: 780px; margin: 0 auto; padding: 8px 20px 40px; }
.page-title { font-family: var(--font-display); font-weight: 400; font-size: 26px; margin-bottom: 14px; color: var(--ink); text-shadow: 0 2px 0 rgba(255,255,255,.6); }
.empty { padding: 30px; text-align: center; background: var(--paper); border: var(--border-w) dashed #c9bd9a; border-radius: var(--radius-lg); color: #7d7894; font-weight: 700; }
.list { list-style: none; display: flex; flex-direction: column; gap: 10px; }
.row { width: 100%; display: flex; align-items: center; gap: 12px; padding: 12px 16px; background: var(--paper); border: var(--border-w) solid var(--ink); border-radius: var(--radius); box-shadow: var(--shadow-pop-sm); text-align: left; }
.row:hover { transform: translateY(-2px); }
.id-chip { font-family: var(--font-num); font-weight: 800; background: var(--paper-dim); border: 2px solid var(--ink); border-radius: 9px; padding: 3px 8px; }
.info { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.title { font-weight: 900; font-size: 15px; }
.sub { font-size: 12px; color: #8a85a0; }
.status { font-size: 11px; font-weight: 900; padding: 2px 9px; border-radius: 999px; border: 2px solid var(--ink); background: var(--paper-dim); }
.status.running { background: #e5f6e0; }
.status.finished { background: #e8f4ff; }
.result { font-size: 12px; font-weight: 900; }
.result.wolf { color: var(--wolf); }
.result.good { color: #4a8a3a; }
</style>
