import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'list', component: () => import('../views/MatchListView.vue') },
  { path: '/create', name: 'create', component: () => import('../views/CreateMatchView.vue') },
  { path: '/matches/:id', name: 'match', component: () => import('../views/MatchView.vue') },
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
})
