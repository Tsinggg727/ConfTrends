import request from './request'

/**
 * Top N 热词榜（功能3 / 原型①）
 * @param {object} params
 * @param {number} [params.year]       统计年份，缺省 = 表里最新一年
 * @param {string} [params.conference] CVPR/ICCV/ECCV，缺省 = 三大会议汇总
 * @param {number} [params.n]          榜单长度，默认 10
 */
export function getTopStats(params) {
  return request.get('/stats/top', { params })
}

/**
 * 热词逐年热度（功能5 走势页 / 原型②）
 * @param {object} params
 * @param {string} [params.keywords]   逗号分隔 keyword id，缺省 = 范围内热度 Top N
 * @param {number} [params.from] [params.to]  年份窗口
 * @param {string} [params.conferences] 逗号分隔会议 code，缺省 = 三大会议
 * @param {number} [params.top_n]      缺省选词数（10，上限 30）
 */
export function getTrend(params) {
  return request.get('/stats/trend', { params })
}
