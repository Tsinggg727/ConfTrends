<script setup>
/**
 * 关键词力导向图谱 —— 功能4 / 原型①。
 * 节点大小 = 热度（heat_norm 缩放），Top1 #F59E0B 高亮；连线 = 同论文
 * 共现（细线低透明，权重越大越醒目）。点节点 → 弹窗展示相关论文
 * （/graph/keywords/{id}/papers 分页），弹窗内可跳论文列表。
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

import { getKeywordGraph, getKeywordPapers } from '@/api/graph'

const TOP1_COLOR = '#F59E0B'
const BASE_COLOR = '#3B82F6'

const year = ref(null)
const conference = ref('')
const years = ref([])
const loading = ref(true)
const empty = ref(false)

const chartEl = ref(null)
let chart = null

const confOptions = [
  { value: '', label: '三大会议汇总' },
  { value: 'CVPR', label: 'CVPR' },
  { value: 'ICCV', label: 'ICCV' },
  { value: 'ECCV', label: 'ECCV' },
]

// ---------- 相关论文弹窗 ----------
const dialogVisible = ref(false)
const dialogKeyword = ref(null)          // { id, name }
const papers = ref([])
const papersTotal = ref(0)
const papersPage = ref(1)
const papersLoading = ref(false)

async function openPapers(node) {
  dialogKeyword.value = node
  dialogVisible.value = true
  papersPage.value = 1
  await loadPapers()
}

async function loadPapers() {
  papersLoading.value = true
  try {
    const data = await getKeywordPapers(dialogKeyword.value.id, {
      page: papersPage.value,
      page_size: 5,
    })
    papers.value = data.list
    papersTotal.value = data.total
  } finally {
    papersLoading.value = false
  }
}

function goPaperList() {
  const name = dialogKeyword.value?.name || ''
  window.location.assign(`/papers?keyword=${encodeURIComponent(name)}`)
}

// ---------- 图谱 ----------
async function load() {
  loading.value = true
  try {
    const data = await getKeywordGraph({
      year: year.value || undefined,
      conference: conference.value || undefined,
      n: 50,
    })
    years.value = data.years
    year.value = data.year ?? data.years?.[0] ?? null
    empty.value = !data.nodes.length
    await nextTick()
    render(data)
  } finally {
    loading.value = false
  }
}

function render({ nodes, edges }) {
  if (!chartEl.value || empty.value) return
  if (!chart) chart = echarts.init(chartEl.value)

  // 节点大小 = 热度：heat_norm 0–100 → 半径 12–46；Top1 奖牌色高亮
  const top1 = nodes.reduce((a, b) => (b.heat_norm > a.heat_norm ? b : a))
  chart.setOption({
    tooltip: {
      formatter: (p) => p.dataType === 'node'
        ? `<b>${p.data.name}</b><br/>DF ${p.data.df} ｜ 热度 ${Number(p.data.heat).toFixed(1)} ｜ 共现边 ${p.data.degree ?? '—'}`
        : `共现 ${p.data.weight} 篇`,
    },
    series: [{
      type: 'graph',
      layout: 'force',
      roam: true,
      draggable: true,
      data: nodes.map((n) => ({
        id: String(n.id),
        name: n.name,
        symbolSize: 12 + (n.heat_norm / 100) * 34,
        itemStyle: { color: n.id === top1.id ? TOP1_COLOR : BASE_COLOR },
        df: n.df,
        heat: n.heat,
        label: { show: n.heat_norm > 45 || n.id === top1.id },
      })),
      links: edges.map((e) => ({
        source: String(e.source),
        target: String(e.target),
        lineStyle: { width: Math.min(1 + e.weight * 0.4, 5), opacity: 0.25 },
      })),
      force: { repulsion: 260, edgeLength: [60, 140], gravity: 0.12 },
      label: { position: 'right', color: '#1F2937' },
      emphasis: { focus: 'adjacency', lineStyle: { opacity: 0.6 } },
      lineStyle: { color: '#94A3B8', curveness: 0.1 },
    }],
  }, true)
  chart.off('click')
  chart.on('click', (p) => {
    if (p.dataType === 'node') openPapers({ id: Number(p.data.id), name: p.data.name })
  })
}

function onResize() {
  chart?.resize()
}

onMounted(async () => {
  window.addEventListener('resize', onResize)
  await load()
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
})
watch([year, conference], load)

const subtitle = computed(() =>
  `${year.value ?? '—'} 年${conference.value ? ` · ${conference.value}` : ' · 三大会议汇总'}`)
</script>

<template>
  <section class="ct-card graph-card">
    <div class="head">
      <h2 class="title">🕸 关键词图谱</h2>
      <span class="sub">{{ subtitle }} · 节点大小 = 热度，连线 = 同论文共现</span>
      <div class="spacer" />
      <el-select v-model="conference" size="small" style="width: 132px">
        <el-option v-for="o in confOptions" :key="o.value"
                   :label="o.label" :value="o.value" />
      </el-select>
      <el-select v-model="year" size="small" style="width: 96px"
                 :disabled="!years.length">
        <el-option v-for="y in years" :key="y" :label="`${y} 年`" :value="y" />
      </el-select>
    </div>

    <div v-if="empty && !loading" class="empty">
      暂无图谱数据 —— 当前口径下没有达到 DF 门槛的关键词
    </div>
    <div v-show="!empty" ref="chartEl" v-loading="loading"
         class="chart" :style="{ height: '440px' }" />
    <p v-if="!empty" class="footnote">点击节点查看相关论文；滚轮缩放，拖拽布局。</p>

    <el-dialog
      v-model="dialogVisible"
      :title="`「${dialogKeyword?.name}」相关论文（${papersTotal} 篇）`"
      width="640px"
    >
      <div v-loading="papersLoading" class="dialog-body">
        <div v-if="!papers.length" class="dialog-empty">没有关联论文</div>
        <div v-for="p in papers" :key="p.id" class="paper-item">
          <router-link :to="`/papers/${p.id}`" class="paper-title">
            {{ p.title }}
          </router-link>
          <div class="paper-meta ct-num">
            {{ p.conf || '—' }} {{ p.year || '' }}
          </div>
        </div>
        <el-pagination
          v-if="papersTotal > 5"
          layout="prev, pager, next"
          :total="papersTotal"
          :page-size="5"
          :current-page="papersPage"
          @current-change="(p) => { papersPage = p; loadPapers() }"
        />
      </div>
      <template #footer>
        <el-button @click="dialogVisible = false">关闭</el-button>
        <el-button type="primary" @click="goPaperList">去论文列表查看 →</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.graph-card {
  margin-top: 16px;
}
.head {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.title {
  margin: 0;
  font-size: 16px;
}
.sub {
  font-size: 12px;
  color: var(--ct-text-sub);
}
.spacer {
  flex: 1;
}
.chart {
  margin-top: 12px;
  width: 100%;
}
.empty {
  padding: 48px 0;
  text-align: center;
  font-size: 13px;
  color: var(--ct-text-sub);
}
.footnote {
  margin: 10px 0 0;
  font-size: 12px;
  color: #9aa4b2;
}
.dialog-body {
  max-height: 380px;
  overflow: auto;
}
.dialog-empty {
  text-align: center;
  padding: 24px 0;
  color: var(--ct-text-sub);
  font-size: 13px;
}
.paper-item {
  padding: 10px 2px;
  border-bottom: 1px solid #eef2f7;
}
.paper-item:last-of-type {
  border-bottom: none;
}
.paper-title {
  color: var(--ct-text);
  font-size: 13px;
  font-weight: 500;
  text-decoration: none;
}
.paper-title:hover {
  color: var(--ct-primary);
}
.paper-meta {
  margin-top: 2px;
  font-size: 12px;
  color: #9aa4b2;
}
</style>
