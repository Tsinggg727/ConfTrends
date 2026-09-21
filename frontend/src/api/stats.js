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
