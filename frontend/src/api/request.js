/**
 * axios 实例：统一 baseURL、超时、响应拆包与错误提示。
 *
 * 后端响应体固定为 { code, message, data }，这里直接把 data 交给调用方，
 * 调用方拿到的就是业务数据本身；出错则抛异常并由拦截器统一弹 Message。
 *
 * 传 `silent: true` 的请求不弹错误提示（错误仍会 reject），给轮询这类
 * 高频请求用 —— 后端短暂不可达时不能每 2 秒弹一次 toast，页面自己
 * 用「无法连接后端」的静态提示表达就够了。
 */
import axios from 'axios'
import { ElMessage } from 'element-plus'

const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/api/v1',
  timeout: 15000,
})

request.interceptors.response.use(
  (response) => {
    const body = response.data

    // 非标准响应体（如二进制流）原样返回
    if (!body || typeof body !== 'object' || !('code' in body)) {
      return body
    }

    if (body.code === 0) {
      return body.data
    }

    if (!response.config?.silent) {
      ElMessage.error(body.message || '请求失败')
    }
    return Promise.reject(new Error(body.message || '请求失败'))
  },
  (error) => {
    const message =
      error.response?.data?.message ||
      (error.code === 'ECONNABORTED' ? '请求超时' : '网络异常，请确认后端服务已启动')
    if (!error.config?.silent) {
      ElMessage.error(message)
    }
    return Promise.reject(error)
  },
)

export default request
