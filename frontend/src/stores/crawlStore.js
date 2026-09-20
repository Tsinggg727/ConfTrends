/**
 * 爬取任务状态 —— 设计文档 §5.3 的前端交互核心。
 *
 * 职责：
 *   · 持有「当前查看的任务」与它的结果行，组件只读这里；
 *   · 每 2s 轮询 GET /tasks/{id}，status 进入终态自动停止；
 *   · task_id 写 localStorage：切走再回来能恢复未完成的任务；
 *   · 轮询期间结果列表走 after_seq 增量，不整表重渲染（滚动位置不丢）。
 *
 * 「当前任务」是页面视图概念，不是队列：历史任务点回查看就是把它设为当前。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  cancelTask,
  commitTask,
  getTask,
  getTaskItems,
  listTasks,
  pauseTask,
  resumeTask,
} from '@/api/crawl'

const ACTIVE_KEY = 'confTrends.activeTaskId'
export const POLL_MS = 2000
const PAGE_SIZE = 20
const TERMINAL = new Set(['done', 'cancelled', 'failed'])
const ACTIVE = new Set(['queued', 'running', 'pausing', 'cancelling'])

export const useCrawlStore = defineStore('crawl', () => {
  // ---------- 当前任务 ----------
  const task = ref(null)                 // GET /tasks/{id} 的 data
  const backendDown = ref(false)         // 轮询连续失败 → 进度条转红 + [重连]
  const submitting = ref(false)          // 提交中（按钮 loading，防重复提交）

  // ---------- 结果列表 ----------
  const rows = ref([])                   // 已加载的结果行（seq 倒序）
  const total = ref(0)
  const filter = ref('all')              // all / success / failed
  const page = ref(1)
  const ignoredSeqs = ref(new Set())     // [忽略] 的失败行：仅前端隐藏，历史任务里仍可查
  let lastSeq = 0                        // 增量游标：已拿到的最大 seq
  let loadedTaskRowId = null             // rows 属于哪个任务（切任务时重置）

  // ---------- 历史任务 ----------
  const history = ref([])
  const historyTotal = ref(0)

  const taskId = computed(() => task.value?.task_id || '')
  const isRunning = computed(() => !!task.value && ACTIVE.has(task.value.status))
  const isTerminal = computed(() => !!task.value && TERMINAL.has(task.value.status))
  const canPause = computed(() => task.value?.status === 'running')
  const canResume = computed(() =>
    ['paused', 'cancelled'].includes(task.value?.status))
  const canCancel = computed(() => !!task.value && !isTerminal.value)
  /** 暂存模式才有「全部入库」；边爬边入库显示静态提示（§5.3） */
  const isStaged = computed(() => !!task.value && !task.value.auto_commit)
  const navBadge = ref(false)            // 导航栏「爬取/导入」的小圆点

  let timer = null

  // ---------------------------------------------------------------
  // 轮询
  // ---------------------------------------------------------------
  function startPolling() {
    stopPolling()
    timer = setInterval(poll, POLL_MS)
  }

  function stopPolling() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  async function poll() {
    if (!taskId.value) return
    try {
      task.value = await getTask(taskId.value)
      backendDown.value = false
    } catch {
      // silent：不弹 toast，页面用「无法连接后端」的红条表达（§5.3 状态表）
      backendDown.value = true
      return
    }
    await refreshItemsIncremental()
    if (isTerminal.value) {
      stopPolling()
      navBadge.value = false
      localStorage.removeItem(ACTIVE_KEY)
      // 终态整页刷新一次，把分页口径（total / 各筛选页）对齐
      await loadItems()
      await loadHistory()
    }
  }

  /** 设为当前任务：running 则开始轮询，否则只拉一次状态 */
  async function watchTask(id, { poll: pollNow = true } = {}) {
    stopPolling()
    resetRows()
    task.value = null
    backendDown.value = false
    localStorage.setItem(ACTIVE_KEY, id)

    try {
      task.value = await getTask(id, { silent: false })
    } catch {
      backendDown.value = true
      return
    }
    lastSeq = 0
    await loadItems()
    if (isTerminal.value) {
      localStorage.removeItem(ACTIVE_KEY)
      return
    }
    navBadge.value = true
    if (pollNow) startPolling()
  }

  /** 页面加载 / 切回本页：恢复未完成任务，没有就恢复上次看过的任务 */
  async function restore() {
    const saved = localStorage.getItem(ACTIVE_KEY)
    if (!saved) {
      await loadHistory()
      return
    }
    try {
      const t = await getTask(saved, { silent: true })
      await watchTask(t.task_id)
    } catch {
      // 任务已被清库（换库/重置）：丢掉指针，页面回到空态
      localStorage.removeItem(ACTIVE_KEY)
      await loadHistory()
    }
  }

  // ---------------------------------------------------------------
  // 结果列表（后端分页筛选；轮询期间增量刷新）
  // ---------------------------------------------------------------
  function resetRows() {
    rows.value = []
    total.value = 0
    page.value = 1
    filter.value = 'all'
    lastSeq = 0
    loadedTaskRowId = null
  }

  async function loadItems() {
    if (!task.value) return
    const id = task.value.task_id
    loadedTaskRowId = id
    const data = await getTaskItems(id, {
      status: filter.value,
      page: page.value,
      page_size: PAGE_SIZE,
    })
    if (id !== loadedTaskRowId) return        // 期间切了任务，丢弃过期响应
    rows.value = data.list
    total.value = data.total
    lastSeq = data.list.length ? Math.max(lastSeq, data.list[0].seq) : lastSeq
  }

  /** 轮询增量：只在第一页插新行 —— 用户翻到后面页时页内容保持稳定 */
  async function refreshItemsIncremental() {
    if (page.value !== 1 || !taskId.value) return
    const data = await getTaskItems(taskId.value, {
      status: filter.value,
      after_seq: lastSeq,
    })
    if (!data.list.length) return
    const known = new Set(rows.value.map((r) => r.seq))
    const fresh = data.list.filter((r) => !known.has(r.seq))
    if (fresh.length) {
      // 行以 seq 为 key，Vue 只 patch 新增的行，已有行不重渲染
      rows.value = [...fresh, ...rows.value]
      total.value += fresh.length
      lastSeq = Math.max(lastSeq, ...fresh.map((r) => r.seq))
    }
  }

  function setFilter(value) {
    filter.value = value
    page.value = 1
    lastSeq = 0
    loadItems()
  }

  function setPage(value) {
    page.value = value
    loadItems()
  }

  function ignoreRow(seq) {
    const next = new Set(ignoredSeqs.value)
    next.add(seq)
    ignoredSeqs.value = next
  }

  const visibleRows = computed(() =>
    rows.value.filter((r) => !ignoredSeqs.value.has(r.seq)))

  // ---------------------------------------------------------------
  // 动作：暂停 / 继续 / 取消 / 入库
  // ---------------------------------------------------------------
  async function pause() {
    if (!taskId.value) return
    await pauseTask(taskId.value)
    // pausing → paused 由轮询确认；若此刻没在轮询（异常态）就拉一次
    if (!timer) await poll()
  }

  async function resume() {
    if (!taskId.value) return
    await resumeTask(taskId.value)
    backendDown.value = false
    startPolling()
    await poll()
  }

  async function cancel() {
    if (!taskId.value) return
    await cancelTask(taskId.value)
    if (!timer) await poll()
  }

  /** 全部入库 → { inserted, updated, skipped_dup }，入库后明细指回了 paper */
  async function commit() {
    const counts = await commitTask(taskId.value)
    await loadItems()
    return counts
  }

  // ---------------------------------------------------------------
  // 历史任务
  // ---------------------------------------------------------------
  async function loadHistory() {
    try {
      const data = await listTasks({ page: 1, page_size: 50 })
      history.value = data.list
      historyTotal.value = data.total
      // 还有没跑完的任务 → 导航角标亮着（跨页面也成立）
      navBadge.value = data.list.some((t) => ACTIVE.has(t.status))
    } catch {
      // 后端未启动：历史面板显示空态即可，错误提示由拦截器统一弹
    }
  }

  return {
    task, taskId, isRunning, isTerminal, canPause, canResume, canCancel,
    isStaged, backendDown, submitting,
    rows, visibleRows, total, filter, page,
    history, historyTotal, navBadge,
    startPolling, stopPolling, poll, watchTask, restore,
    loadItems, setFilter, setPage, ignoreRow,
    pause, resume, cancel, commit, loadHistory,
  }
})
