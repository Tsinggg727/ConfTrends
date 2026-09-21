<script setup>
/**
 * ② 热度走势对比（原型② / 功能5）。
 * ECharts 折线逐年生长动画 + 底部年份进度条（可点跳帧）+ 播放/暂停居中 +
 * 图例可点击显隐 + 悬停 tooltip 四要素（年份/会议/热词/热度）。
 * 会议多选限定 CVPR/ICCV/ECCV；数据来自 GET /stats/trend（复用
 * hot_keyword_stat，data 保留 conference 维度，前端按年聚合画线）。
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

import { getTrend } from '@/api/stats'

/* 低饱和三色族调色板（视觉评审定稿：哑光金 / 墨蓝 / 雾紫及中性扩展） */
const PALETTE = ['#C9A85C', '#4C6FB6', '#7B6FC0', '#8F7333', '#3A5590',
  '#9B8CCB', '#B08250', '#64707F', '#AEB6C2', '#7B8A9E']
const FRAME_MS = 3000                        // 帧间隔 = 动画时长：每 3s 沿轴推进一年（视觉反馈）

const conferences = ref(['CVPR', 'ICCV', 'ECCV'])
const years = ref([])                        // 窗口内的全部年份（升序）
const series = ref([])                       // 每词一条：data 按 (year, conference)
const loading = ref(true)

const frame = ref(0)                         // 当前播放到的年份下标
const playing = ref(false)
let timer = null

const chartEl = ref(null)
let chart = null

const confOptions = [
  { value: 'CVPR', label: 'CVPR' },
  { value: 'ICCV', label: 'ICCV' },
  { value: 'ECCV', label: 'ECCV' },
]

const progress = computed(() =>
  years.value.length ? ((frame.value + 1) / years.value.length) * 100 : 0)

/** X 轴固定为全部年份（2022–2026），不随播放帧变化 */
const xData = computed(() => years.value)

/** 第 frame 帧的系列：数据点逐个追加（只含 years[0..frame] 的点）。
 *  每词每年的热度 = 该年各选中会议 heat 之和；tooltip 的会议明细随行携带。 */
const frameSeries = computed(() => {
  const n = frame.value + 1
  const shown = new Set(years.value.slice(0, n))
  return series.value.map((s) => {
    const byYear = {}
    for (const d of s.data) {
      if (!shown.has(d.year)) continue
      byYear[d.year] = byYear[d.year] || { total: 0, confs: [] }
      byYear[d.year].total += d.heat
      byYear[d.year].confs.push({ conference: d.conference, freq: d.freq, heat: d.heat })
    }
    return {
      name: s.name,
      type: 'line',
      smooth: true,
      symbolSize: 7,
      data: years.value.slice(0, n).map((y) => byYear[y]
        ? { value: Number(byYear[y].total.toFixed(1)), confs: byYear[y].confs }
        : { value: 0, confs: [] }),
      lineStyle: { width: 2.4 },
      emphasis: { focus: 'series' },
    }
  })
})

async function render(replaceSeries = false) {
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value)
  await nextTick()   // 等布局生效（v-show 刚翻转时容器可能还没完成布局）
  chart.resize()     // 容器尺寸可能已变化，重测后再绘制
  chart.setOption({
    color: PALETTE,
    animationDuration: 3000,
    animationEasing: 'cubicOut',
    animationDurationUpdate: 3000,
    animationEasingUpdate: 'cubicOut',
    grid: { left: 56, right: 24, top: 36, bottom: 40 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(15, 23, 42, .94)',
      borderWidth: 0,
      textStyle: { color: '#fff', fontSize: 12 },
      formatter: (params) => {
        const year = params[0]?.axisValue ?? ''
        let html = `<b>${year} 年</b>`
        for (const p of params) {
          const confs = p.data.confs || []
          const detail = confs.length
            ? confs.map((c) => `${c.conference} ${c.heat}`).join(' / ')
            : '无数据'
          html += `<div style="display:flex;justify-content:space-between;gap:16px;">` +
            `<span>${p.marker} ${p.seriesName}</span>` +
            `<span style="margin-left:auto;">${p.value}</span></div>` +
            `<div style="color:#93C5FD;font-size:11px;margin-left:18px;">${detail}</div>`
        }
        return html
      },
    },
    legend: {
      type: 'scroll',
      top: 0,
      icon: 'circle',
      itemWidth: 10,
      textStyle: { fontSize: 12 },
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: xData.value,
      axisLine: { lineStyle: { color: '#E2E8F0' } },
      axisLabel: { color: '#6B7280' },
    },
    yAxis: {
      type: 'value',
      name: '热度',
      nameTextStyle: { color: '#9AA4B2' },
      splitLine: { lineStyle: { color: '#F1F5F9' } },
      axisLabel: { color: '#6B7280' },
    },
    series: frameSeries.value,
  },
  // 合并式更新：只增量变更 series 数据，动画表现为「沿 X 轴追加生长」；
  // replaceSeries=true 时（重载/切换口径）整体替换，清掉不再存在的旧系列
  replaceSeries ? { replaceMerge: ['series'] } : undefined)
}

// ---------- 播放控制 ----------
function setFrame(i) {
  frame.value = Math.max(0, Math.min(years.value.length - 1, i))
}

function stepFrame(delta) {
  if (playing.value) togglePlay()
  setFrame(frame.value + delta)
}

function togglePlay() {
  playing.value = !playing.value
  if (playing.value) {
    if (frame.value >= years.value.length - 1) setFrame(0)   // 从头播
    timer = setInterval(() => {
      if (frame.value >= years.value.length - 1) {
        togglePlay()
        return
      }
      setFrame(frame.value + 1)
    }, FRAME_MS)
  } else if (timer) {
    clearInterval(timer)
    timer = null
  }
}

function seekFromTrack(event) {
  const rect = event.currentTarget.getBoundingClientRect()
  const ratio = (event.clientX - rect.left) / rect.width
  if (playing.value) togglePlay()
  setFrame(Math.round(ratio * (years.value.length - 1)))
}

async function load() {
  loading.value = true
  try {
    const data = await getTrend({
      conferences: conferences.value.join(','),
      top_n: 10,
    })
    years.value = data.years
    series.value = data.series
    frame.value = years.value.length ? years.value.length - 1 : 0
    await nextTick()
    render()
  } finally {
    loading.value = false
  }
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
  if (timer) clearInterval(timer)
  chart?.dispose()
  chart = null
})
watch(conferences, load)
watch(loading, (v) => {
  if (!v) render(true)          // 新语料加载完成：整体替换（清掉旧关键词系列）
})
watch(frameSeries, () => render())   // 播放/追加帧：合并式增量更新
</script>

<template>
  <div class="trend-view">
    <div class="page-head">
      <h1 class="page-title">热度走势对比</h1>
      <p class="page-sub">
        时间轴上的每条折线代表一个热词（热度 = 词频 × 年份增长率，
        按选中会议逐年聚合）；点击图例可显隐曲线，悬停查看年份 / 会议 / 热词 / 热度。
      </p>
    </div>

    <section class="ct-card">
      <div class="filters">
        <span class="label">会议</span>
        <el-checkbox-group v-model="conferences">
          <el-checkbox v-for="o in confOptions" :key="o.value"
                       :value="o.value">{{ o.label }}</el-checkbox>
        </el-checkbox-group>
        <span class="label">曲线</span>
        <el-select size="small" style="width: 90px"
                   :model-value="10" @update:model-value="load">
          <el-option label="Top 5" :value="5" />
          <el-option label="Top 10" :value="10" />
          <el-option label="Top 15" :value="15" />
        </el-select>
        <span class="hint ct-num">{{ years[0] || '—' }}–{{ years[years.length - 1] || '—' }}</span>
      </div>

      <el-skeleton v-if="loading" :rows="6" animated style="margin-top: 16px" />
      <div v-show="!loading" ref="chartEl" class="chart" :style="{ height: '420px' }" />
      <div v-if="!loading && !years.length" class="empty">
        暂无热度数据 —— 论文入库并重算统计后这里会出现走势
      </div>

      <!-- 播放控制条（原型②：年份进度 + 上一帧/下一帧 + 播放居中） -->
      <div class="player" :class="{ disabled: !years.length }">
        <div class="track-row">
          <span class="label">年份进度</span>
          <div class="track" @click="seekFromTrack">
            <div class="fill" :style="{ transform: `scaleX(${progress / 100})` }" />
          </div>
          <span class="frame ct-num">
            {{ years[frame] || '—' }}
          </span>
        </div>
        <div class="controls">
          <el-button size="small" :disabled="!years.length" @click="stepFrame(-1)">
            上一帧
          </el-button>
          <el-button
            type="primary"
            class="play-btn"
            :disabled="!years.length"
            @click="togglePlay"
          >
            <svg v-if="!playing" class="ic" style="width:.875rem;height:.875rem" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.5v13l10-6.5z"/></svg>
            <svg v-else class="ic" style="width:.875rem;height:.875rem" viewBox="0 0 24 24" fill="currentColor"><rect x="7" y="5" width="3.5" height="14" rx="1"/><rect x="13.5" y="5" width="3.5" height="14" rx="1"/></svg>
            {{ playing ? '暂停' : '播放动图' }}
          </el-button>
          <el-button size="small" :disabled="!years.length" @click="stepFrame(1)">
            下一帧
          </el-button>
          <span class="chip ct-num">每年 3 秒</span>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.trend-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.page-head {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.page-title {
  margin: 0;
  font-size: 22px;
}
.page-sub {
  margin: 0;
  font-size: 13px;
  color: var(--ct-text-sub);
  max-width: 760px;
}
.filters {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.label {
  font-size: 12px;
  color: #9aa4b2;
}
.hint {
  margin-left: auto;
  font-size: 13px;
  color: var(--ct-text-sub);
}
.chart {
  margin-top: 16px;
  width: 100%;
}
.empty {
  padding: 40px 0;
  text-align: center;
  font-size: 13px;
  color: var(--ct-text-sub);
}
.player {
  margin-top: 18px;
  padding: 14px 16px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid #eef2f7;
}
.player.disabled {
  opacity: 0.5;
  pointer-events: none;
}
.track-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.track {
  flex: 1;
  height: 8px;
  border-radius: 999px;
  background: #e2e8f0;
  cursor: pointer;
  overflow: hidden;
}
.fill {
  height: 100%;
  width: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--ct-primary), var(--ct-secondary));
  transform: scaleX(0);                        /* 进度用 scaleX 表现，宽度恒定 */
  transform-origin: left;
  transition: transform 2.8s linear;           /* 与帧间隔(3s)接近，视觉同步 */
}
.frame {
  width: 48px;
  text-align: right;
  font-size: 13px;
  font-weight: 600;
}
.controls {
  margin-top: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
}
.play-btn {
  padding-left: 24px;
  padding-right: 24px;
}
.chip {
  font-size: 12px;
  padding: 3px 9px;
  border-radius: 999px;
  background: #fff7ed;
  color: #b45309;
}
</style>
