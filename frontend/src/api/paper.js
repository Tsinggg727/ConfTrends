import request from './request'

/**
 * 论文列表
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
