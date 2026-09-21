import request from './request'

/**
 * 关键词图谱（功能4 / 原型①）
 * @param {object} params { year, conference, n } —— 口径同 /stats/top，
 *                        n = 节点数上限（默认 50）
 */
export function getKeywordGraph(params) {
  return request.get('/graph/keywords', { params })
}

/** 某关键词下的相关论文（分页） */
export function getKeywordPapers(keywordId, params) {
  return request.get(`/graph/keywords/${keywordId}/papers`, { params })
}
