<script setup lang="ts">
// 对局列表页：静态导出源（exports/index.json）；本地文件打开入口
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMatchListStore } from '../stores/matchList'
import { useReplayStore } from '../stores/replay'

const store = useMatchListStore()
const replay = useReplayStore()
const router = useRouter()
const fileInput = ref<HTMLInputElement | null>(null)
const picking = ref(false)

onMounted(() => void store.refresh())

const statusLabel: Record<string, string> = {
  finished: '已结束',
  stopped: '已终止',
  running: '进行中',
  created: '准备中',
}

function open(id: number) {
  router.push(`/matches/${id}`)
}

async function onPick(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  picking.value = true
  try {
    await replay.loadLocal(file)
    if (replay.error) {
      alert(replay.error)
      return
    }
    router.push('/matches/local')
  } finally {
    picking.value = false
  }
}
</script>

<template>
  <nav class="topbar">
    <p class="brand"><span class="logo">🐺</span><span class="word">whoisspy</span></p>
    <button class="new-btn" :disabled="picking" @click="fileInput?.click()">
      📂 打开本地复盘
    </button>
    <input
      ref="fileInput"
      class="hidden-input"
      type="file"
      accept=".json,application/json"
      @change="onPick"
    />
  </nav>

  <main class="wrap">
    <h1 class="page-title">对局列表</h1>
    <p v-if="store.loading" class="empty">加载中……</p>
    <p v-else-if="store.error" class="empty err">
      无法读取对局索引：{{ store.error }}
    </p>
    <div v-else-if="!store.matches.length" class="empty">
      <p>还没有对局。先在 backend/ 跑一局：</p>
      <code class="cmd">python -m app.main --mock --seed 42</code>
      <p class="hint">或者用「打开本地复盘」直接读单份导出文件。</p>
    </div>
    <ul v-else class="list">
      <li v-for="m in store.matches" :key="m.match_id">
        <button class="row" @click="open(m.match_id)">
          <span class="id-chip">#{{ m.match_id }}</span>
          <span class="info">
            <span class="title">狼人杀 · {{ m.player_count }} 人局</span>
            <span class="sub">种子 {{ m.seed }} · {{ m.exported_at.slice(0, 10) }}</span>
          </span>
          <span class="status" :class="m.status">
            {{ statusLabel[m.status] ?? m.status }}
          </span>
          <span v-if="m.winner" class="result" :class="m.winner">
            {{ m.winner === 'wolf' ? '🐺 狼胜' : '👍 好人胜' }}
          </span>
          <span class="views">
            <span v-for="v in m.views" :key="v" class="view-chip">{{ v }}</span>
          </span>
        </button>
      </li>
    </ul>
  </main>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 20px;
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
.new-btn {
  margin-left: auto;
  padding: 8px 16px;
  font-size: 14px;
  font-weight: 900;
  background: var(--paper);
  border: var(--border-w) solid var(--ink);
  border-radius: 999px;
  box-shadow: var(--shadow-pop-sm);
}
.new-btn:hover { transform: translateY(-1px); }
.new-btn:disabled { opacity: 0.5; cursor: wait; }
.hidden-input { display: none; }
.wrap { max-width: 780px; margin: 0 auto; padding: 8px 20px 40px; }
.page-title {
  font-family: var(--font-display);
  font-weight: 400;
  font-size: 26px;
  margin-bottom: 14px;
  color: var(--ink);
  text-shadow: 0 2px 0 rgba(255, 255, 255, 0.6);
}
.empty {
  padding: 30px;
  text-align: center;
  background: var(--paper);
  border: var(--border-w) dashed #c9bd9a;
  border-radius: var(--radius-lg);
  color: #7d7894;
  font-weight: 700;
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: center;
}
.empty.err { color: var(--wolf); }
.cmd {
  font-size: 13px;
  background: var(--ink);
  color: var(--paper);
  padding: 6px 12px;
  border-radius: 9px;
}
.hint { font-size: 12.5px; color: #9b97a8; }
.list { list-style: none; display: flex; flex-direction: column; gap: 10px; }
.row {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: var(--paper);
  border: var(--border-w) solid var(--ink);
  border-radius: var(--radius);
  box-shadow: var(--shadow-pop-sm);
  text-align: left;
}
.row:hover { transform: translateY(-2px); }
.id-chip {
  font-family: var(--font-num);
  font-weight: 800;
  background: var(--paper-dim);
  border: 2px solid var(--ink);
  border-radius: 9px;
  padding: 3px 8px;
}
.info { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.title { font-weight: 900; font-size: 15px; }
.sub { font-size: 12px; color: #8a85a0; }
.status {
  font-size: 11px;
  font-weight: 900;
  padding: 2px 9px;
  border-radius: 999px;
  border: 2px solid var(--ink);
  background: var(--paper-dim);
}
.status.finished { background: #e8f4ff; }
.result { font-size: 12px; font-weight: 900; }
.result.wolf { color: var(--wolf); }
.result.good { color: #4a8a3a; }
.views { display: flex; gap: 4px; }
.view-chip {
  font-size: 10px;
  font-weight: 900;
  color: #55507a;
  background: #f3f0fa;
  border: 1.5px solid var(--ink);
  border-radius: 999px;
  padding: 1px 7px;
}
</style>