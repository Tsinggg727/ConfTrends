<script setup>
/**
 * 批量题目面板 —— 设计 §5.1 BatchTitlePanel。
 * 粘贴 / 上传 .txt/.csv 二选一；两者同时提供时以文件为准并提示（§5.3）。
 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { importPapers } from '@/api/crawl'
import { useCrawlStore } from '@/stores/crawlStore'

const store = useCrawlStore()

const mode = ref('paste')                 // paste / file
const text = ref('')
const fileList = ref([])
const submitting = computed(() => store.submitting)

/** 文件优先：选了文件就提示粘贴内容会被忽略 */
function onFileChange(file, files) {
  fileList.value = files.slice(-1)        // 只保留最后一个
  if (files.length && text.value.trim()) {
    ElMessage.info('已选择文件，粘贴的内容将被忽略')
  }
}

async function submit() {
  store.submitting = true
  try {
    let data
    if (mode.value === 'file' && fileList.value.length) {
      const form = new FormData()
      form.append('type', 'titles')
      form.append('file', fileList.value[0].raw)
      data = await importPapers(form)
    } else {
      if (!text.value.trim()) {
        ElMessage.warning('请粘贴题目列表，每行一个题目')
        return
      }
      data = await importPapers({ type: 'titles', text: text.value })
    }
    ElMessage.success(data.message || `识别到 ${data.total} 条，已开始抓取`)
    await store.watchTask(data.task_id)
  } finally {
    store.submitting = false
  }
}
</script>

<template>
  <div class="batch-panel">
    <el-radio-group v-model="mode" class="mode-group">
      <el-radio-button value="paste">粘贴列表</el-radio-button>
      <el-radio-button value="file">上传 .txt / .csv</el-radio-button>
    </el-radio-group>

    <el-input
      v-if="mode === 'paste'"
      v-model="text"
      type="textarea"
      :rows="8"
      placeholder="每行一个论文题目…"
      class="textarea"
    />
    <el-upload
      v-else
      v-model:file-list="fileList"
      drag
      :auto-upload="false"
      :limit="1"
      accept=".txt,.csv"
      :on-change="onFileChange"
      :on-remove="() => (fileList = [])"
      class="upload"
    >
      <div class="upload-hint">
        <div>将 .txt / .csv 拖到此处，或点击选择</div>
        <div class="sub">CSV 只取第一列（题目列），每行一个题目，上限 5000 条</div>
      </div>
    </el-upload>

    <div class="actions">
      <el-button type="primary" :loading="submitting" @click="submit">
        开始爬取
      </el-button>
      <span class="hint">默认暂存不写库，跑完确认后点「全部入库」</span>
    </div>
  </div>
</template>

<style scoped>
.mode-group {
  margin-bottom: 14px;
}
.textarea {
  margin-bottom: 4px;
}
.upload {
  width: 100%;
}
.upload :deep(.el-upload-dragger) {
  width: 100%;
}
.upload-hint {
  padding: 12px 0;
  font-size: 13px;
  color: var(--ct-text-sub);
}
.upload-hint .sub {
  margin-top: 6px;
  font-size: 12px;
  color: #9aa4b2;
}
.actions {
  margin-top: 14px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.hint {
  font-size: 12px;
  color: var(--ct-text-sub);
}
</style>
