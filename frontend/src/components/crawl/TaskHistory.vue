<script setup>
/**
 * 历史任务列表 —— 设计 §5.1 TaskHistory。
 * 长时任务的基本保障：刷新/关页面后能找回任务；点「查看」切为当前任务，
 * 没跑完的还能续跑（paused / cancelled）。
 */
import { computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'

import { useCrawlStore } from '@/stores/crawlStore'
import { statusMeta, TYPE_LABELS } from '@/constants/crawl'

const store = useCrawlStore()

const rows = computed(() => store.history)

onMounted(() => {
  store.loadHistory()
})

function fmtTime(value) {
  return value ? String(value).replace('T', ' ').slice(0, 19) : '—'
}

async function view(row) {
  await store.watchTask(row.task_id)
}

async function resumeRow(row) {
  await store.watchTask(row.task_id)
  if (store.canResume) {
    await store.resume()
    ElMessage.success('已从断点继续')
  }
}
</script>

<template>
  <section class="ct-card history-card">
    <h2 class="history-title">历史任务</h2>

    <el-empty
      v-if="!rows.length"
      description="还没有任务记录，从上方任一方式开始第一次爬取"
      :image-size="72"
    />

    <ul v-else class="list">
      <li v-for="row in rows" :key="row.task_id" class="item">
        <div class="line-1">
          <el-tag :type="statusMeta(row.status).tag" size="small" effect="light">
            {{ statusMeta(row.status).label }}
          </el-tag>
          <span class="type">{{ TYPE_LABELS[row.type] || row.type }}</span>
          <span class="ct-num target">
            {{ row.conference_code || '不限会议' }} {{ row.year || '' }}
          </span>
          <span class="ct-num progress">
            {{ row.finished }}/{{ row.total }}（{{ row.percent }}%）
          </span>
          <span class="time ct-num">{{ fmtTime(row.created_at) }}</span>
        </div>
        <div v-if="row.pause_label" class="pause-label">{{ row.pause_label }}</div>
        <div class="line-2">
          <el-button size="small" text type="primary" @click="view(row)">
            查看
          </el-button>
          <el-button
            v-if="['paused', 'cancelled'].includes(row.status)"
            size="small"
            text
            type="success"
            @click="resumeRow(row)"
          >
            续跑
          </el-button>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.history-card {
  margin-top: 16px;
}
.history-title {
  margin: 0 0 8px;
  font-size: 15px;
}
.list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.item {
  padding: 10px 4px;
  border-bottom: 1px solid #eef2f7;
}
.item:last-child {
  border-bottom: none;
}
.line-1 {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 13px;
}
.type {
  font-weight: 500;
}
.target {
  color: var(--ct-text);
}
.progress {
  color: var(--ct-text-sub);
}
.time {
  margin-left: auto;
  font-size: 12px;
  color: #9aa4b2;
}
.pause-label {
  margin-top: 4px;
  font-size: 12px;
  color: #b45309;
}
.line-2 {
  margin-top: 2px;
}
</style>
