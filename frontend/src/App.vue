<script setup lang="ts">
// App：天空场景层 + 路由出口（观赛/列表/创建共用昼夜背景）
import { provide, ref } from 'vue'
import SkyBackdrop from './components/SkyBackdrop.vue'

// 全局视角状态：god 视角由各视图经 store 管理，这里提供全局 key 给天空层用
const globalPhase = ref<'night' | 'day'>('day')
provide('globalPhase', globalPhase)
</script>

<template>
  <SkyBackdrop :phase="globalPhase" />
  <RouterView />
</template>
