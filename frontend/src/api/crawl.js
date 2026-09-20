/**
 * 爬取 / 导入相关接口 —— 设计文档 §4.1 / §4.2。
 *
 * 单条爬取是同步接口（一届限定时约 5–20s），超时放宽到 120s；
 * 批量导入是异步接口，拿到 task_id 后轮询 GET /tasks/{task_id}。
 */
import request from './request'

/** 单个题目爬取（同步）。body: { title, conference_code?, year?, auto_commit? } */
export function crawlSingle(data) {
  return request.post('/papers/crawl', data, { timeout: 120000 })
}

/** 批量导入（异步）。data 为 JSON 或 FormData（bibtex 文件上传）。 */
export function importPapers(data) {
  const isForm = data instanceof FormData
  return request.post('/papers/import', data, isForm
    ? { headers: { 'Content-Type': 'multipart/form-data' } }
    : {})
}

/** 任务进度查询（每 2s 轮询；silent 避免后端抖动时刷 toast） */
export function getTask(taskId, { silent = true } = {}) {
  return request.get(`/tasks/${taskId}`, { silent })
}

/**
 * 任务结果行分页。
 * @param {object} params { status: 'all'|'success'|'failed', page, page_size, after_seq }
 *   after_seq 传上次最大 seq 即「只给增量」，供轮询期间把新完成的行插到顶部。
 */
export function getTaskItems(taskId, params) {
  return request.get(`/tasks/${taskId}/items`, { params, silent: true })
}

/** 任务列表（历史任务面板） */
export function listTasks(params) {
  return request.get('/tasks', { params })
}

/** 暂存模式的「全部入库」→ { inserted, updated, skipped_dup } */
export function commitTask(taskId) {
  return request.post(`/tasks/${taskId}/commit`)
}

/** 手动暂停（运行中返回 pausing，由轮询确认终态） */
export function pauseTask(taskId) {
  return request.post(`/tasks/${taskId}/pause`)
}

/** 从断点续跑 */
export function resumeTask(taskId) {
  return request.post(`/tasks/${taskId}/resume`)
}

/** 取消任务（已完成部分保留） */
export function cancelTask(taskId) {
  return request.post(`/tasks/${taskId}/cancel`)
}

/**
 * 失败项重试 → 返回**新任务**（{ task_id, total, poll_url }）。
 * @param {number[]|undefined} itemIds 缺省 = 全部可重试项；传单个 id 即行内 [重试]
 */
export function retryTask(taskId, itemIds) {
  return request.post(`/tasks/${taskId}/retry`,
    itemIds ? { item_ids: itemIds } : {})
}
