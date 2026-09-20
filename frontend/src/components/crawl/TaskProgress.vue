<script setup>
/**
 * 任务进度区 —— 设计 §5.1 TaskProgress / §5.2 进度四要素。
 * 阶段文案 + 总进度条 + 分类计数 + 速率/ETA；暂停/继续按钮也在这一区（§5.2）。
 * 后端不可达时进度条转红 + [重连]（§5.3 状态表）。
 */
import { computed } from 'vue'
import { ElMessage } from 'element-plus'

import { useCrawlStore } from '@/stores/crawlStore'
import { statusMeta, TYPE_LABELS } from '@/constants/crawl'

const store = useCrawlStore()

const task = computed(() => store.task)
const meta = computed(() => statusMeta(task.value?.status))
const stageLabel = computed(() => {
  if (!task.value) return ''
  if (task.value.status === 'pausing') return '正在收尾当前这一篇…'
  return task.value.stage_label || task.value.stage
})

const percent = computed(() => task.value?.percent ?? 0)
const qps = computed(() => task.value?.qps ?? 0)
const etaText = computed(() => {
  const eta = task.value?.eta_sec
  if (eta === null || eta === undefined) return '—'
  if (eta === 0) return '已完成'
  if (eta < 60) return `${eta} 秒`
  return `${Math.ceil(eta / 60)} 分钟`
})

/** §5.3：速率掉到 0 而任务还在跑 → 黄字提示可能被限流 */
const slowHint = computed(() =>
  store.isRunning && qps.value === 0 && (task.value?.finished ?? 0) > 0)

function etaOrDash(value) {
  return value === null || value === undefined ? '—' : value
}

async function togglePause() {
  if (store.canResume) {
    await store.resume()
    ElMessage.success('已从断点继续')
  } else {
    await store.pause()
    ElMessage.info('已请求暂停，当前这一篇完成后停手')
  }
}

function reconnect() {
  store.backendDown = false
  store.startPolling()
  store.poll()
}
</script>

<template>
  <section v-if="task" class="ct-card progress-card">
    <div class="head">
      <div class="title">
        <span class="ct-num task-id">{{ TYPE_LABELS[task.type] || task.type }}
          · {{ task.conference_code || '不限会议' }} {{ task.year || '' }}</span>
        <el-tag :type="meta.tag" size="small" effect="light">{{ meta.label }}</el-tag>
      </div>
      <div class="controls">
        <el-button
          v-if="store.canPause || store.canResume"
          size="small"
          @click="togglePause"
        >
          {{ store.canPause ? '⏸ 暂停' : '▶ 继续' }}
        </el-button>
      </div>
    </div>

    <div v-if="store.backendDown" class="down-bar">
      无法连接后端，任务状态未知
      <el-button size="small" type="danger" plain @click="reconnect">重连</el-button>
    </div>

    <el-progress
      :percentage="percent"
      :status="store.backendDown ? 'exception' : undefined"
      :stroke-width="12"
      class="bar"
    />

    <div class="stats ct-num">
      <span>阶段：{{ stageLabel }}</span>
      <span class="ok">✓ 成功 {{ task.success }}</span>
      <span class="bad">✗ 失败 {{ task.failed }}</span>
      <span class="skip">⊘ 跳过 {{ task.skipped ?? 0 }}</span>
      <span>{{ qps }} 篇/秒</span>
      <span>预计剩余 {{ etaText }}</span>
      <span>{{ task.finished }}/{{ task.total }}</span>
    </div>

    <div v-if="task.current_title" class="current">
      正在处理：{{ task.current_title }}
    </div>
    <div v-if="task.pause_label" class="pause-note">
      ⚠ {{ task.pause_label }}（可点「继续」从断点续跑）
    </div>
    <div v-if="slowHint" class="slow-hint">
      当前速率较低，可能正在被限流，请耐心等待
    </div>
  </section>
</template>

<style scoped>
.progress-card {
  margin-top: 16px;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  font-weight: 600;
}
.stats {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  margin-top: 10px;
  font-size: 13px;
  color: var(--ct-text-sub);
}
.stats .ok { color: var(--ct-success); }
.stats .bad { color: var(--ct-danger); }
.current {
  margin-top: 10px;
  font-size: 13px;
  color: var(--ct-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.pause-note {
  margin-top: 10px;
  font-size: 13px;
  color: #b45309;
}
.slow-hint {
  margin-top: 8px;
  font-size: 12px;
  color: #b45309;
}
.down-bar {
  margin-top: 12px;
  padding: 10px 14px;
  border-radius: 8px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: var(--ct-danger);
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.bar {
  margin-top: 14px;
}
</style>
