/**
 * 任务状态与类型的展示映射。
 * （会议-年份日历已改为从 GET /api/v1/crawl/units 动态拉取，
 * 见 stores/unitsStore.js —— 不再在这里手工镜像后端数据。）
 */

/** 任务状态 → 展示文案与 Element Plus tag 类型 */
export const STATUS_META = {
  queued: { label: '排队中', tag: 'info' },
  running: { label: '运行中', tag: 'primary' },
  pausing: { label: '暂停中…', tag: 'warning' },
  cancelling: { label: '取消中…', tag: 'warning' },
  paused: { label: '已暂停', tag: 'warning' },
  done: { label: '已完成', tag: 'success' },
  cancelled: { label: '已取消', tag: 'info' },
  failed: { label: '已失败', tag: 'danger' },
}

/** 任务类型 → 展示文案 */
export const TYPE_LABELS = {
  single: '单条爬取',
  batch_titles: '批量题目',
  bibtex: 'BibTeX 导入',
  unit: '整届导入',
}

export function statusMeta(status) {
  return STATUS_META[status] || { label: status, tag: 'info' }
}
