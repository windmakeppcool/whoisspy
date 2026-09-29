// 静态导出源：fetch <base>/index.json 与 match-<id>-<view>.json
// dev：Vite 中间件把 /exports/ 挂到 ../backend/exports；部署：构建产物与 exports/ 同源托管。
import { parseDisplayDoc, type DisplayDoc, type MatchSummary, type View } from '../model/display'
import type { MatchSource } from './MatchSource'

const BASE = (import.meta.env.VITE_EXPORTS_BASE as string | undefined) ?? '/exports'

async function getJson(path: string): Promise<unknown> {
  const resp = await fetch(`${BASE}/${path}`)
  if (!resp.ok) throw new Error(`读取失败（${resp.status}）：${path}`)
  return resp.json()
}

export const staticExportSource: MatchSource = {
  async list(): Promise<MatchSummary[]> {
    const index = (await getJson('index.json')) as { matches?: MatchSummary[] }
    return index.matches ?? []
  },
  async load(matchId: number, view: View): Promise<DisplayDoc> {
    return parseDisplayDoc(await getJson(`match-${matchId}-${view}.json`))
  },
}