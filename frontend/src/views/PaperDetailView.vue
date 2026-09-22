<script setup>
/**
 * 论文详情 —— 原型⑤ 的基础版（功能2「查看」的落点）。
 * 左栏：题目 + 关键词标签（点击回列表按词过滤）+ 摘要；
 * 右栏：会议年份 / 来源 / PDF 原文与摘要页外链。
 * 「相关论文」闭环需要相似度计算（功能2统计侧），不在本版范围。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { getPaper } from '@/api/paper'
import { useUnitsStore } from '@/stores/unitsStore'

const route = useRoute()
const router = useRouter()
const unitsStore = useUnitsStore()

const paper = ref(null)
const loading = ref(true)

/** 会议全称只在「该会议确实办过这一年」时展示（日历来自 /crawl/units） */
const venue = computed(() => {
  const code = paper.value?.conference?.code
  if (!code) return ''
  return unitsStore.yearsOf(code).includes(paper.value.year)
    ? paper.value.conference.name
    : ''
})

/** 原文 = PDF 直链（爬虫抓详情页时存进 pdf_url）；缺 PDF 的老数据退回摘要页 */
const pdfLink = computed(() => paper.value?.pdf_url || paper.value?.url || '')

function hostOf(url) {
  try {
    return new URL(url).host
  } catch {
    return ''
  }
}

onMounted(async () => {
  // 日历用于会议全称校验，失败不影响详情展示（venue 退化为空）
  if (!unitsStore.units.length) unitsStore.load()
  try {
    paper.value = await getPaper(route.params.id)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div v-loading="loading" class="paper-detail">
    <template v-if="paper">
      <div class="detail-grid">
        <section class="ct-card main-col">
          <div class="code-line ct-num">论文编码：{{ paper.id }}</div>
          <h1 class="title">{{ paper.title }}</h1>
          <div class="kw-line">
            <el-tag
              v-for="kw in paper.keywords"
              :key="kw"
              size="small"
              effect="plain"
              class="kw"
              @click="router.push({ path: '/papers', query: { keyword: kw } })"
            >
              {{ kw }}
            </el-tag>
            <span v-if="!paper.keywords.length" class="no-kw">
              暂无关键词（关键词抽取属阶段五）
            </span>
          </div>
          <div class="abstract-block">
            <h2 class="block-title">摘要</h2>
            <p class="abstract">{{ paper.abstract || '摘要缺失' }}</p>
          </div>
        </section>

        <aside class="ct-card side-col">
          <h2 class="block-title">论文信息</h2>
          <dl class="meta">
            <dt>会议</dt>
            <dd>
              <el-tag size="small" effect="plain">
                {{ paper.conference?.code || '—' }}
              </el-tag>
              <span v-if="venue" class="venue">{{ venue }}</span>
            </dd>
            <dt>年份</dt>
            <dd class="ct-num">{{ paper.year || '—' }}</dd>
            <dt>来源</dt>
            <dd>{{ paper.source }}</dd>
            <dt>补全状态</dt>
            <dd>{{ paper.enrich_status }}</dd>
            <dt>原文</dt>
            <dd>
              <a v-if="pdfLink" :href="pdfLink" target="_blank" rel="noopener">
                {{ hostOf(pdfLink) }} ↗
              </a>
              <span v-else>—</span>
            </dd>
            <dt v-if="paper.url">摘要页</dt>
            <dd v-if="paper.url">
              <a :href="paper.url" target="_blank" rel="noopener">
                {{ hostOf(paper.url) }} ↗
              </a>
            </dd>
            <dt v-if="paper.doi">DOI</dt>
            <dd v-if="paper.doi" class="ct-num">{{ paper.doi }}</dd>
          </dl>
        </aside>
      </div>
    </template>

    <section v-else-if="!loading" class="ct-card">
      <el-empty description="论文不存在或已删除">
        <el-button type="primary" @click="router.push('/papers')">返回列表</el-button>
      </el-empty>
    </section>
  </div>
</template>

<style scoped>
.detail-grid {
  display: grid;
  grid-template-columns: 1.7fr 1fr;
  gap: 16px;
  align-items: start;
}
@media (max-width: 900px) {
  .detail-grid {
    grid-template-columns: 1fr;
  }
}
.title {
  font-size: 20px;
  line-height: 1.5;
  margin: 0 0 14px;
}
.code-line {
  font-size: 13px;
  color: #9aa4b2;
  margin-bottom: 6px;
}
.kw-line {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 18px;
}
.kw {
  color: #2563eb;
  cursor: pointer;
}
.kw:hover {
  border-color: var(--ct-primary);
}
.no-kw {
  font-size: 12px;
  color: #9aa4b2;
}
.block-title {
  font-size: 14px;
  margin: 0 0 10px;
  color: var(--ct-text);
}
.abstract {
  font-size: 14px;
  line-height: 1.9;
  color: var(--ct-text-sub);
  margin: 0;
}
.meta {
  margin: 0;
  display: grid;
  grid-template-columns: 76px 1fr;
  row-gap: 12px;
  font-size: 13px;
}
.meta dt {
  color: #9aa4b2;
}
.meta dd {
  margin: 0;
  color: var(--ct-text);
}
.venue {
  display: block;
  margin-top: 6px;
  font-size: 12px;
  color: var(--ct-text-sub);
  line-height: 1.6;
}
.meta a {
  color: #2563eb;
  text-decoration: none;
}
.meta a:hover {
  text-decoration: underline;
}
</style>
