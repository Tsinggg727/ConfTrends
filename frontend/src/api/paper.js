import request from './request'

/**
 * 论文列表（功能2 / 原型③）
 * @param {object} params
 * @param {string} [params.q]          检索词
 * @param {'exact'|'fuzzy'} [params.mode]  精确=按题目 / 模糊=题目+编号+关键词
 * @param {string} [params.keyword]    按关键词名过滤（首页、详情页跳转用）
 * @param {string[]} [params.conference] 会议 code 多选
 * @param {number[]} [params.year]     年份多选
 * @param {number} [params.page]
 * @param {number} [params.page_size]
 */
export function listPapers(params) {
  return request.get('/papers', { params })
}

/** 论文详情（含关键词列表） */
export function getPaper(id) {
  return request.get(`/papers/${id}`)
}

/** 手工新增论文（source='manual'） */
export function createPaper(data) {
  return request.post('/papers', data)
}

/** 编辑论文（改题目会触发同题判重） */
export function updatePaper(id, data) {
  return request.put(`/papers/${id}`, data)
}

/** 软删除（status='deleted'，可恢复） */
export function deletePaper(id) {
  return request.delete(`/papers/${id}`)
}

/** 恢复软删除的论文 */
export function restorePaper(id) {
  return request.post(`/papers/${id}/restore`)
}
