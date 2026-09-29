// 本地文件源：拖拽/选择打开单个导出 JSON，零部署分享复盘
// 单文件即单视角（文档自带 view）；视角切换按钮在本地态禁用。
import { parseDisplayDoc, type DisplayDoc, type MatchSummary } from '../model/display'
import type { MatchSource } from './MatchSource'

export const localFileSource: MatchSource = {
  async list(): Promise<MatchSummary[]> {
    return []
  },
  async load(): Promise<DisplayDoc> {
    throw new Error('本地文件源不支持按编号加载')
  },
}

export async function parseLocalFile(file: File): Promise<DisplayDoc> {
  let value: unknown
  try {
    value = JSON.parse(await file.text())
  } catch {
    throw new Error('文件不是合法 JSON')
  }
  return parseDisplayDoc(value)
}