/**
 * 可抓取单元日历 —— GET /api/v1/crawl/units 的前端缓存（§1.0）。
 *
 * 会议/年份下拉的唯一数据源：后端 units.py 实测确认的组合，前端不再
 * 手工镜像（那份数据改一次要同步两个文件，漏了就是下拉与校验口径不一致）。
 * `nearestYear` 是纯函数，单独导出供测试。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { listUnits } from '@/api/crawl'

/** 从候选年份里挑离 target 最近的一届；并列取更大的一届（更新的数据） */
export function nearestYear(years, target) {
  if (!years.length) return undefined
  return years.reduce((a, b) =>
    Math.abs(b - target) < Math.abs(a - target) ? b : a)
}

export const useUnitsStore = defineStore('units', () => {
  const units = ref([])
  const loading = ref(false)
  const error = ref(null)

  async function load() {
    if (loading.value) return
    loading.value = true
    error.value = null
    try {
      const data = await listUnits()
      units.value = data.units
    } catch (err) {
      // 静默请求：不弹全局 toast，下拉置灰 + 页面内的失败态/重试来兜
      error.value = err
    } finally {
      loading.value = false
    }
  }

  const conferenceCodes = computed(() =>
    [...new Set(units.value.map((u) => u.conference_code))])

  /** 某会议可选的年份（后端已按从新到旧排序） */
  function yearsOf(code) {
    return units.value
      .filter((u) => u.conference_code === code)
      .map((u) => u.year)
  }

  function unitOf(code, year) {
    return units.value.find((u) => u.conference_code === code && u.year === year) || null
  }

  return { units, loading, error, load, conferenceCodes, yearsOf, unitOf }
})
