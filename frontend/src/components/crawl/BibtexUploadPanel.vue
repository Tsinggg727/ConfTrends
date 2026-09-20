<script setup>
/**
 * BibTeX / 整届导入面板 —— 设计 §5.1 BibtexUploadPanel。
 * 两种模式：
 *   bibtex —— 上传 .bib（会议 + 年份必填），默认边爬边入库；
 *   unit   —— 不传文件，平台自己去列表页拉整届清单。
 * 整届动辄 2000–3000 篇、约 40–60 分钟，启动前必须把时间成本摆明（§5.3）。
 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { importPapers } from '@/api/crawl'
import { CONFERENCE_CODES, CONFERENCE_UNITS } from '@/constants/crawl'
import { useCrawlStore } from '@/stores/crawlStore'

const store = useCrawlStore()

const mode = ref('bibtex')                // bibtex / unit
const conference = ref('CVPR')
const year = ref(2024)
const autoCommit = ref(true)              // 整届建议勾选（§5.2 原型）
const fileList = ref([])
const entryCount = ref(0)                 // 从 .bib 文本数出来的记录条数
const submitting = computed(() => store.submitting)

const yearOptions = computed(() => CONFERENCE_UNITS[conference.value] || [])

async function onFileChange(file, files) {
  fileList.value = files.slice(-1)
  entryCount.value = 0
  const raw = fileList.value[0]
  if (!raw) return
  // 在浏览器里粗数一遍 @type{ 记录，给「识别到 N 篇」的预览（§5.3）
  try {
    const text = await raw.raw.text()
    entryCount.value = (text.match(/@\w+\s*\{/g) || []).length
  } catch {
    entryCount.value = 0
  }
}

function onFileRemove() {
  fileList.value = []
  entryCount.value = 0
}

function validate() {
  if (!conference.value || !year.value) {
    ElMessage.warning('BibTeX / 整届导入必须明确会议与年份')
    return false
  }
  if (mode.value === 'bibtex' && !fileList.value.length) {
    ElMessage.warning('请选择 .bib 文件')
    return false
  }
  return true
}

async function submit() {
  if (!validate()) return
  store.submitting = true
  try {
    let data
    if (mode.value === 'bibtex') {
      const form = new FormData()
      form.append('type', 'bibtex')
      form.append('conference_code', conference.value)
      form.append('year', String(year.value))
      form.append('auto_commit', autoCommit.value ? 'true' : 'false')
      form.append('file', fileList.value[0].raw)
      data = await importPapers(form)
    } else {
      data = await importPapers({
        type: 'unit',
        conference_code: conference.value,
        year: year.value,
        auto_commit: autoCommit.value,
      })
    }
    ElMessage.success(`识别到 ${data.total} 条，已开始抓取`)
    await store.watchTask(data.task_id)
  } finally {
    store.submitting = false
  }
}
</script>

<template>
  <div class="bibtex-panel">
    <el-radio-group v-model="mode" class="mode-group">
      <el-radio-button value="bibtex">上传 .bib</el-radio-button>
      <el-radio-button value="unit">整届清单（不传文件）</el-radio-button>
    </el-radio-group>

    <el-upload
      v-if="mode === 'bibtex'"
      v-model:file-list="fileList"
      drag
      :auto-upload="false"
      :limit="1"
      accept=".bib"
      :on-change="onFileChange"
      :on-remove="onFileRemove"
      class="upload"
    >
      <div class="upload-hint">
        <div>将 .bib 文件拖到此处，或点击选择（≤ 5MB）</div>
        <div class="sub">从 CVF Open Access 每届的「Citation BibTeX」导出</div>
      </div>
    </el-upload>

    <div class="target-row">
      <el-select v-model="conference" style="width: 130px">
        <el-option v-for="code in CONFERENCE_CODES" :key="code"
                   :label="code" :value="code" />
      </el-select>
      <el-select v-model="year" style="width: 130px" @change="() => {}">
        <el-option v-for="y in yearOptions" :key="y" :label="y" :value="y" />
      </el-select>
      <el-checkbox v-model="autoCommit">写入数据库（整届建议勾选）</el-checkbox>
    </div>

    <el-alert
      v-if="mode === 'bibtex' && entryCount"
      :title="`已识别 ${conference} ${year}，共 ${entryCount} 篇`"
      type="info"
      :closable="false"
      class="count-alert"
    />
    <el-alert
      title="整届约 2000–3000 篇，按限速抓取预计 40–60 分钟；可随时暂停、离开页面，进度自动保留。"
      type="warning"
      :closable="false"
      class="count-alert"
    />

    <div class="actions">
      <el-button type="primary" :loading="submitting" @click="submit">
        开始爬取
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.mode-group {
  margin-bottom: 14px;
}
.upload {
  width: 100%;
  margin-bottom: 4px;
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
.target-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 12px 0;
}
.count-alert {
  margin-bottom: 10px;
}
</style>
