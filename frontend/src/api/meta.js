import request from './request'

/** 导航栏数据标签 + 首页 Hero 统计条 */
export function getSummary() {
  return request.get('/meta/summary')
}

/** 后端存活探针 */
export function getHealth() {
  return request.get('/meta/health')
}
