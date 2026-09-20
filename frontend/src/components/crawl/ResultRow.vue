<script setup>
/**
 * 单行结果 —— 设计 §5.1 ResultRow。
 * 成功行三字段：摘要（2 行截断 + tooltip）/ 关键词标签 / 原文链接；
 * 失败行：人话文案 + 失败码标签，可重试的给 [重试]（步骤 7 接后端），
 * 不可重试的给 [忽略]（前端隐藏，历史任务里仍可查）。
 */
import { computed } from 'vue'

const props = defineProps({
  row: { type: Object, required: true },
})
defineEmits(['ignore', 'retry'])

const isSuccess = computed(() => props.row.status === 'success')
const paper = computed(() => props.row.paper || {})
const abstract = computed(() => paper.value.abstract || '')
const host = computed(() => {
  try {
    return new URL(paper.value.url).host
  } catch {
    return ''
  }
})

/** 失败码 → 简短标签（完整人话文案在 fail_message 里） */
const codeLabel = computed(() => props.row.fail_reason || '')
</script>

<template>
  <div class="result-row" :class="{ failed: !isSuccess }">
    <span class="mark" :class="isSuccess ? 'ok' : 'bad'">
      {{ isSuccess ? '✓' : '✗' }}
    </span>

    <div class="body">
      <div class="title-line">
        <span class="title">{{ paper.title || row.input_title }}</span>
        <span v-if="paper.conference_code" class="conf ct-num">
          {{ paper.conference_code }} {{ paper.year || '' }}
        </span>
      </div>

      <template v-if="isSuccess">
        <el-tooltip
          v-if="abstract"
          :content="abstract"
          placement="top"
          :show-after="200"
          popper-class="abstract-popper"
        >
          <div class="abstract">{{ abstract }}</div>
        </el-tooltip>
        <div v-else class="abstract missing">
          摘要缺失（Semantic Scholar 未收录）
        </div>

        <div class="meta-line">
          <el-tag
            v-for="kw in (row.keywords || []).slice(0, 6)"
            :key="kw"
            size="small"
            effect="plain"
            class="kw"
          >
            {{ kw }}
          </el-tag>
          <a
            v-if="paper.url"
            class="origin"
            :href="paper.url"
            target="_blank"
            rel="noopener"
          >
            {{ host }} ↗
          </a>
        </div>
      </template>

      <div v-else class="fail-line">
        <span class="fail-message">{{ row.fail_message || '抓取失败' }}</span>
        <el-tag v-if="codeLabel" size="small" type="danger" effect="plain">
          {{ codeLabel }}
        </el-tag>
        <el-button
          v-if="row.retryable"
          size="small"
          text
          type="primary"
          @click="$emit('retry', row.id)"
        >
          重试
        </el-button>
        <el-button
          v-else
          size="small"
          text
          type="info"
          @click="$emit('ignore', row.seq)"
        >
          忽略
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.result-row {
  display: flex;
  gap: 10px;
  padding: 12px 4px;
  border-bottom: 1px solid #eef2f7;
}
.result-row:last-child {
  border-bottom: none;
}
.mark {
  font-weight: 700;
  line-height: 1.5;
}
.mark.ok { color: var(--ct-success); }
.mark.bad { color: var(--ct-danger); }
.body {
  flex: 1;
  min-width: 0;
}
.title-line {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.title {
  font-size: 14px;
  font-weight: 500;
}
.conf {
  font-size: 12px;
  color: var(--ct-text-sub);
  white-space: nowrap;
}
.abstract {
  margin-top: 4px;
  font-size: 12px;
  color: var(--ct-text-sub);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  cursor: default;
}
.abstract.missing {
  color: #9aa4b2;
  font-style: italic;
}
.meta-line {
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.kw {
  color: #2563eb;
}
.origin {
  font-size: 12px;
  color: #2563eb;
  text-decoration: none;
}
.origin:hover {
  text-decoration: underline;
}
.fail-line {
  margin-top: 4px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.fail-message {
  color: var(--ct-text-sub);
}
</style>
