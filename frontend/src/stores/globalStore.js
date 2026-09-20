import { defineStore } from 'pinia'
import { ref } from 'vue'

import { getSummary } from '@/api/meta'

/**
 * 全局状态：导航栏的年份下拉与数据标签。
 * 年份在这一处切换，首页榜单/图谱、走势页、列表页都读它。
 */
export const useGlobalStore = defineStore('global', () => {
  const year = ref(new Date().getFullYear())

  const summary = ref({
    paper_count: 0,
    keyword_count: 0,
    conference_count: 0,
    updated_at: null,
    year_range: [2022, 2026],
  })

  async function loadSummary() {
    try {
      summary.value = await getSummary()
    } catch {
      // 后端未启动时保持默认值，页面不空白；错误提示已由 axios 拦截器统一弹出
    }
  }

  function setYear(value) {
    year.value = value
  }

  return { year, summary, loadSummary, setYear }
})
