// 数据源抽象：静态导出目录 / 本地文件（阶段 B 预留 ApiSource，接口不变）
import type { DisplayDoc, MatchSummary, View } from '../model/display'

export interface MatchSource {
  /** 对局索引（列表页）；本地文件源返回空。 */
  list(): Promise<MatchSummary[]>
  /** 展示文档（复盘页）；本地文件源不支持按编号加载。 */
  load(matchId: number, view: View): Promise<DisplayDoc>
}