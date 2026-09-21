import request from './request'

/**
 * 会议信息（关于页卡片 / 筛选栏选项数据源，系统设计 §3.2）。
 * silent：关于页对请求失败有内置降级文案，不需要全局 toast。
 */
export function getConferences() {
  return request.get('/conferences', { silent: true })
}

/** 单个会议 */
export function getConference(code) {
  return request.get(`/conferences/${code}`)
}
