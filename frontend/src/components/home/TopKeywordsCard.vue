<script setup>
/**
 * Top10 热门方向榜单 —— 功能3 / 原型①。
 * ECharts 横向条形图：条长由 heat_norm 驱动（系统设计 §2.5），
 * Top1 #F59E0B / Top2 银 / Top3 铜；年份与会议口径可切换；
 * 点条目 → 论文列表按该词过滤（与关键词标签行为一致）。
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

import { getTopStats } from '@/api/stats'

const MEDALS = { 1: '#F59E0B', 2: '#C0C4CC', 3: '#CD7F32' }
const BASE_COLOR = '#3B82F6'

const year = ref(null)
const conference = ref('')               // '' = 三大会议汇总
const years = ref([])
const list = ref([])
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

async function load() {
  loading.value = true
  try {
    const data = await getTopStats({
      year: year.value || undefined,
      conference: conference.value || undefined,
      n: 10,
    })
    years.value = data.years
    list.value = data.list
    // 年份缺省 = 后端给的最新一年；响应里带回来便于联动
    year.value = data.year ?? data.years?.[0] ?? null
    empty.value = !data.list.length
    await nextTick()
    render()
  } finally {
    loading.value = false
  }
}

function render() {
  if (!chartEl.value || empty.value) return
  if (!chart) chart = echarts.init(chartEl.value)

  // rank 升序的数据在 yAxis 上要倒着放，Top1 才显示在最上面
  const rows = [...list.value].reverse()
  chart.setOption({
    grid: { left: 8, right: 56, top: 8, bottom: 24, containLabel: true },
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(15, 23, 42, .94)',
      borderWidth: 0,
      textStyle: { color: '#fff', fontSize: 12 },
      formatter: (p) => {
        const r = list.value[list.value.length - 1 - p.dataIndex]
        const growth = r.growth_rate > 0 ? `↑ ${(r.growth_rate * 100).toFixed(0)}%`
          : '首年/新词'
        return `<b>${r.name}</b>（第 ${r.rank} 名）<br/>` +
          `词频 ${r.freq} ｜ 上年 ${r.prev_freq} ｜ ${growth}<br/>` +
          `热度 ${Number(r.heat).toFixed(1)}`
      },
    },
    xAxis: { type: 'value', max: 100, splitLine: { show: false }, axisLabel: { show: false } },
    yAxis: {
      type: 'category',
      data: rows.map((r) => r.name),
      axisTick: { show: false },
      axisLine: { show: false },
      axisLabel: { color: '#1F2937', fontSize: 13 },
    },
    series: [{
      type: 'bar',
      barWidth: 18,
      data: rows.map((r) => ({
        value: r.heat_norm,
        itemStyle: {
          color: MEDALS[r.rank] || BASE_COLOR,
          borderRadius: [0, 6, 6, 0],
        },
      })),
      label: {
        show: true,
        position: 'right',
        color: '#6B7280',
        fontSize: 12,
        formatter: (p) => Number(list.value[list.value.length - 1 - p.dataIndex].heat).toFixed(0),
      },
    }],
  })
  chart.off('click')
  chart.on('click', (p) => {
    const name = list.value[list.value.length - 1 - p.dataIndex]?.name
    if (name) window.location.assign(`/papers?keyword=${encodeURIComponent(name)}`)
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
  <section class="ct-card top-card">
    <div class="head">
      <h2 class="title">🔥 Top10 热门方向</h2>
      <span class="sub">{{ subtitle }}</span>
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
      暂无热度数据 —— 论文入库后执行
      <code class="ct-num">POST /api/v1/stats/rebuild</code> 重算统计
    </div>
    <div v-show="!empty" ref="chartEl" v-loading="loading"
         class="chart ct-num" :style="{ height: '320px' }" />
    <p class="footnote">
      热度 = 词频 × 年份增长率；条长为 scope 内归一化热度。新爬届次的关键词
      抽取重建后自动补齐。
    </p>
  </section>
</template>

<style scoped>
.top-card {
  margin-top: 16px;
}
.head {
  display: flex;
  align-items: center;
  gap: 12px;
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
  padding: 40px 0;
  text-align: center;
  font-size: 13px;
  color: var(--ct-text-sub);
}
.footnote {
  margin: 10px 0 0;
  font-size: 12px;
  color: #9aa4b2;
}
</style>
