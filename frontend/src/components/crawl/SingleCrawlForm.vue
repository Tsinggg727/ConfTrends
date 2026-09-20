<script setup>
/**
 * 单条爬取表单 —— 设计 §5.1 SingleCrawlForm。
 * 会议/年份是「加速开关」：不限定要依次检索 9 个单元（分钟级），
 * 限定后只查一届索引（约 5–20s）。接口同步返回，按钮 loading 到结果回来。
 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { crawlSingle } from '@/api/crawl'
import { CONFERENCE_UNITS } from '@/constants/crawl'
import { useCrawlStore } from '@/stores/crawlStore'
import { useGlobalStore } from '@/stores/globalStore'

const store = useCrawlStore()
const globalStore = useGlobalStore()

const title = ref('')
const conference = ref('')
const year = ref('')

/** 年份下拉随会议联动；ECCV 只有 2022/2024 可选 */
const yearOptions = computed(() =>
  conference.value ? CONFERENCE_UNITS[conference.value] : [])

/** 默认限定到全局年份附近可抓的最近一届，与导航栏年份一致（§5.3） */
const globalYear = computed(() => Number(globalStore.year))

function onConferenceChange() {
  const years = CONFERENCE_UNITS[conference.value] || []
  // 换会议后年份可能不合法：尽量吸附到与全局年份最近的可行届
  year.value = years.length
    ? years.reduce((a, b) => (Math.abs(b - globalYear.value) < Math.abs(a - globalYear.value) ? b : a))
    : ''
}

const submitting = computed(() => store.submitting)

async function submit() {
  if (!title.value.trim()) {
    ElMessage.warning('请输入论文完整题目')
    return
  }
  store.submitting = true
  try {
    // 单条是同步接口：响应即终态（含 task_id），统一走 watchTask 展示结果
    const data = await crawlSingle({
      title: title.value.trim(),
      conference_code: conference.value || undefined,
      year: year.value || undefined,
      auto_commit: false,
    })
    await store.watchTask(data.task_id)
    ElMessage.success(data.status === 'success' ? '爬取成功' : '未找到该论文，见结果列表')
  } finally {
    store.submitting = false
  }
}
</script>

<template>
  <div class="single-form">
    <div class="row">
      <el-input
        v-model="title"
        placeholder="输入论文完整题目，如：Diffusion Models Beat GANs on Image Synthesis"
        clearable
        @keyup.enter="submit"
      />
      <el-button
        type="primary"
        class="submit-btn"
        :loading="submitting"
        @click="submit"
      >
        开始爬取
      </el-button>
    </div>
    <div class="row sub-row">
      <span class="hint">限定会议与年份可大幅加速</span>
      <el-select v-model="conference" placeholder="会议：不限定" clearable
                 style="width: 150px" @change="onConferenceChange">
        <el-option v-for="code in Object.keys(CONFERENCE_UNITS)"
                   :key="code" :label="code" :value="code" />
      </el-select>
      <el-select v-model="year" placeholder="年份：不限定" clearable
                 style="width: 150px" :disabled="!conference">
        <el-option v-for="y in yearOptions" :key="y" :label="y" :value="y" />
      </el-select>
    </div>
  </div>
</template>

<style scoped>
.single-form .row {
  display: flex;
  gap: 12px;
  align-items: center;
}
.sub-row {
  margin-top: 12px;
}
.submit-btn {
  flex-shrink: 0;
}
.hint {
  font-size: 12px;
  color: var(--ct-text-sub);
}
</style>
