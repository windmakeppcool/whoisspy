// 本地文件源测试：拖拽/选择打开单份导出 JSON
import { describe, expect, it } from 'vitest'
import { parseLocalFile } from './localFile'
import fixture from '../model/__fixtures__/match-god.json'

describe('parseLocalFile', () => {
  it('解析合法导出文件', async () => {
    const file = new File([JSON.stringify(fixture)], 'match-7-god.json', {
      type: 'application/json',
    })
    const doc = await parseLocalFile(file)
    expect(doc.match_id).toBe(7)
    expect(doc.view).toBe('god')
  })

  it('拒绝坏 JSON', async () => {
    const file = new File(['{oops'], 'bad.json')
    await expect(parseLocalFile(file)).rejects.toThrow(/JSON/)
  })

  it('拒绝 v1 文档（无 stage）', async () => {
    const v1 = JSON.parse(JSON.stringify(fixture))
    delete v1.segments[0].stage
    const file = new File([JSON.stringify(v1)], 'v1.json')
    await expect(parseLocalFile(file)).rejects.toThrow(/重新导出/)
  })
})