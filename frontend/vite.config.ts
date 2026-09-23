import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 设计稿阶段保持零额外配置
export default defineConfig({
  plugins: [vue()],
})
