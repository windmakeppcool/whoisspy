import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'list', component: () => import('../views/MatchListView.vue') },
  { path: '/matches/:id', name: 'match', component: () => import('../views/MatchView.vue') },
  { path: '/matches/local', name: 'local', component: () => import('../views/MatchView.vue') },
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
})