import { describe, expect, it, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

// mock 掉 axios 层：store 逻辑不依赖网络
vi.mock('@/api/crawl', () => ({
  listUnits: vi.fn(),
  crawlSingle: vi.fn(),
  importPapers: vi.fn(),
}))

import { listUnits } from '@/api/crawl'
import { nearestYear, useUnitsStore } from '@/stores/unitsStore'

/** 与后端 /crawl/units 契约一致的样例（从新到旧，实测/估值混合） */
const CALENDAR = {
  total: 9,
  units: [
    { conference_code: 'CVPR', year: 2026, source: 'cvf', available: true,
      expected_papers: null, papers_measured: false, est_papers_min: 2000, est_papers_max: 2800 },
    { conference_code: 'CVPR', year: 2025, source: 'cvf', available: true,
      expected_papers: null, papers_measured: false, est_papers_min: 2000, est_papers_max: 2800 },
    { conference_code: 'ICCV', year: 2025, source: 'cvf', available: true,
      expected_papers: null, papers_measured: false, est_papers_min: 2000, est_papers_max: 2800 },
    { conference_code: 'CVPR', year: 2024, source: 'cvf', available: true,
      expected_papers: 2716, papers_measured: true, est_papers_min: 2000, est_papers_max: 2800 },
    { conference_code: 'ECCV', year: 2024, source: 'ecva', available: true,
      expected_papers: 2387, papers_measured: true, est_papers_min: 2000, est_papers_max: 2800 },
    { conference_code: 'CVPR', year: 2023, source: 'cvf', available: true,
      expected_papers: null, papers_measured: false, est_papers_min: 2000, est_papers_max: 2800 },
    { conference_code: 'ICCV', year: 2023, source: 'cvf', available: true,
      expected_papers: 2156, papers_measured: true, est_papers_min: 2000, est_papers_max: 2800 },
    { conference_code: 'CVPR', year: 2022, source: 'cvf', available: true,
      expected_papers: null, papers_measured: false, est_papers_min: 2000, est_papers_max: 2800 },
    { conference_code: 'ECCV', year: 2022, source: 'ecva', available: true,
      expected_papers: null, papers_measured: false, est_papers_min: 2000, est_papers_max: 2800 },
  ],
}

describe('nearestYear（年份联动吸附）', () => {
  const ECCV_YEARS = [2024, 2022]

  it('精确命中返回该年', () => {
    expect(nearestYear(ECCV_YEARS, 2024)).toBe(2024)
  })

  it('不合法的年份吸附到最近的可抓届', () => {
    expect(nearestYear(ECCV_YEARS, 2023)).toBe(2024)   // 2023 与 2024/2022 等距 → 取更大
    expect(nearestYear(ECCV_YEARS, 2026)).toBe(2024)   // ECCV 2026 未放榜
    expect(nearestYear(ECCV_YEARS, 1999)).toBe(2022)
  })

  it('空列表返回 undefined', () => {
    expect(nearestYear([], 2024)).toBeUndefined()
  })
})

describe('useUnitsStore（下拉数据源）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('load 拉取日历，会议去重、年份按接口顺序', async () => {
    listUnits.mockResolvedValue(CALENDAR)
    const store = useUnitsStore()

    await store.load()

    expect(store.units).toHaveLength(9)
    expect(store.conferenceCodes).toEqual(['CVPR', 'ICCV', 'ECCV'])
    expect(store.yearsOf('ECCV')).toEqual([2024, 2022])   // 从新到旧
    expect(store.yearsOf('ICCV')).toEqual([2025, 2023])
    expect(store.error).toBeNull()
  })

  it('请求失败落 error，不抛到调用方', async () => {
    listUnits.mockRejectedValue(new Error('网络异常'))
    const store = useUnitsStore()

    await store.load()

    expect(store.units).toEqual([])
    expect(store.error).toBeTruthy()
  })

  it('unitOf 命中实测/估值两种条目', async () => {
    listUnits.mockResolvedValue(CALENDAR)
    const store = useUnitsStore()
    await store.load()

    expect(store.unitOf('CVPR', 2024).expected_papers).toBe(2716)
    expect(store.unitOf('CVPR', 2024).papers_measured).toBe(true)
    expect(store.unitOf('ECCV', 2022).expected_papers).toBeNull()
    expect(store.unitOf('ECCV', 2026)).toBeNull()          // 日历里没有的组合
  })
})
