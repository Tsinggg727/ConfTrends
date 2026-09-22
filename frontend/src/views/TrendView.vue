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
const topN = ref(10)                         // 曲线数：Top N 热词（传后端 top_n）
const years = ref([])                        // 窗口内的全部年份（升序）
const loading = ref(true)

const frame = ref(0)                         // 当前播放到的年份下标
const playing = ref(false)

const chartEl = ref(null)
let chart = null

/* —— 扫描线动画（需求2/3）：线的呈现由 cutX 驱动 ——
 * cutX = 线当前画到的 X（年份值，可为小数）。rAF 每帧重算
 * 「截断到 cutX + 末端插值点」，已画过的段数据不变 = 不重画；
 * ECharts 自身动画全关（animation:false），杜绝「上下平移」。 */
let cutX = 0
let scanRaf = null
const yMax = ref(0)                          // Y 轴固定上限（需求1）
const xMin = ref(2022)
const xMax = ref(2026)

/** 加工后的每词数据：points 按年升序 [{ year, value, confs }] */
let linesData = []

const confOptions = [
  { value: 'CVPR', label: 'CVPR' },
  { value: 'ICCV', label: 'ICCV' },
  { value: 'ECCV', label: 'ECCV' },
]

const progress = computed(() =>
  years.value.length ? ((frame.value + 1) / years.value.length) * 100 : 0)

/** 热度上限向上取整到好看的刻度（Y 轴固定用，需求1） */
function niceCeil(v) {
  if (!Number.isFinite(v) || v <= 0) return 10
  const exp = Math.floor(Math.log10(v))
  const steps = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]
  return ((steps.find((s) => v / 10 ** exp <= s)) ?? 10) * 10 ** exp
}

/** 按 cutX 构造当前 series：line = 落定点 + 末端插值点（从左边点长向
 *  右边点，需求2）；scatter = 已落定的点（cut 扫过哪年哪年现点）。
 *  数值轴下空年没有占位点，线自动跨过（单选双年会自然连线）。 */
function buildSeries() {
  return linesData.flatMap((l) => {
    const seg = []
    const dots = []
    let prev = null                        // 上一个已落定实点 { x, v }
    for (const pt of l.points) {
      if (pt.year <= cutX) {
        const item = { value: [pt.year, pt.value], confs: pt.confs }
        seg.push(item)
        dots.push(item)
        prev = { x: pt.year, v: pt.value }
      } else {
        if (prev) {
          const f = (cutX - prev.x) / (pt.year - prev.x)
          seg.push({ value: [cutX, prev.v + (pt.value - prev.v) * f], confs: pt.confs })
        }
        break
      }
    }
    return [
      {
        name: l.name,
        type: 'line',
        smooth: true,
        showSymbol: false,
        symbolSize: 0,
        data: seg,
        color: l.color,
        lineStyle: { width: 2.4, color: l.color },
        emphasis: { focus: 'series' },
      },
      {
        name: l.name,
        type: 'scatter',
        data: dots,
        symbolSize: 7,
        color: l.color,
        itemStyle: { color: l.color },
        silent: true,
        z: 3,
      },
    ]
  })
}

function applyDisplay() {
  if (!chart) return
  chart.setOption({ series: buildSeries() })
}

function cancelScan() {
  if (scanRaf) {
    cancelAnimationFrame(scanRaf)
    scanRaf = null
  }
}

/** 线从当前 cutX 延伸到 targetX：只有末端插值点在动，旧段静止（需求3）。
 *  onDone：本段长完后的回调（播放循环用它衔接下一段）。 */
function scanTo(targetX, dur = FRAME_MS, onDone = null) {
  cancelScan()
  const fromX = cutX
  if (targetX <= fromX) {
    cutX = targetX
    applyDisplay()
    onDone?.()
    return
  }
  const start = performance.now()
  const ease = (t) => 1 - Math.pow(1 - t, 3)     // cubicOut，与原节奏一致
  const tick = (now) => {
    const t = Math.min((now - start) / dur, 1)
    cutX = fromX + (targetX - fromX) * ease(t)
    applyDisplay()
    if (t < 1) scanRaf = requestAnimationFrame(tick)
    else onDone?.()
  }
  scanRaf = requestAnimationFrame(tick)
}

/** 帧推进：向前 = 扫描延伸；向后/跳帧 = 瞬间到位（不重放整线） */
function transitionTo(i, onDone = null) {
  frame.value = Math.max(0, Math.min(years.value.length - 1, i))
  const targetX = years.value[frame.value]
  if (targetX == null) {
    onDone?.()
    return
  }
  if (targetX >= cutX) scanTo(targetX, FRAME_MS, onDone)
  else {
    cancelScan()
    cutX = targetX
    applyDisplay()
    onDone?.()
  }
}

async function startChart() {
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value)
  await nextTick()   // 等布局生效（v-show 刚翻转时容器可能还没完成布局）
  chart.resize()     // 容器尺寸可能已变化，重测后再绘制
  chart.setOption({
    color: PALETTE,
    animation: false,   // 自带动画全关（会「上下平移」）：呈现由扫描线驱动
    grid: { left: 56, right: 24, top: 36, bottom: 40 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(15, 23, 42, .94)',
      borderWidth: 0,
      textStyle: { color: '#fff', fontSize: 12 },
      formatter: (params) => {
        const year = Math.round(params[0]?.axisValue ?? 0)
        let html = `<b>${year} 年</b>`
        for (const p of params) {
          if (p.seriesType !== 'line') continue    // 点与线同名成对，tooltip 只取线
          const v = Array.isArray(p.value) ? p.value[1] : p.value
          if (v == null) continue
          const confs = p.data.confs || []
          const detail = confs.length
            ? confs.map((c) => `${c.conference} ${c.heat}`).join(' / ')
            : '无数据'
          html += `<div style="display:flex;justify-content:space-between;gap:16px;">` +
            `<span>${p.marker} ${p.seriesName}</span>` +
            `<span style="margin-left:auto;">${v}</span></div>` +
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
      type: 'value',      // 数值轴：末端插值点可落在年份之间（线连续生长）
      min: xMin.value,
      max: xMax.value,
      interval: 1,
      axisLine: { lineStyle: { color: '#E2E8F0' } },
      axisLabel: { color: '#6B7280', formatter: (v) => `${v}` },
    },
    yAxis: {
      type: 'value',
      name: '热度',
      min: 0,
      max: yMax.value || null,   // 固定上限：所有年份共用同一刻度（需求1）
      nameTextStyle: { color: '#9AA4B2' },
      splitLine: { lineStyle: { color: '#F1F5F9' } },
      axisLabel: { color: '#6B7280' },
    },
    series: [],
  }, true)   // notMerge：重载/切换口径后旧系列整体清掉
  cancelScan()
  cutX = xMin.value
  applyDisplay()
  // 初始加载：线从 2022 出发沿 X 轴生长到 2026（需求2）
  if (years.value.length > 1) scanTo(xMax.value, FRAME_MS)
}

// ---------- 播放控制 ----------
/** 播完一段接下一段：扫描自链式调度，不与动画抢跑 */
function playNext() {
  if (!playing.value) return
  if (frame.value >= years.value.length - 1) {
    playing.value = false          // 最后一段已长满，自动收停
    return
  }
  transitionTo(frame.value + 1, playNext)
}

function stepFrame(delta) {
  if (playing.value) togglePlay()
  transitionTo(frame.value + delta)
}

function togglePlay() {
  playing.value = !playing.value
  if (playing.value) {
    // 从头播，或从冻结处补完当前段再链下一段
    if (frame.value >= years.value.length - 1) transitionTo(0, playNext)
    else transitionTo(frame.value, playNext)
  } else {
    cancelScan()                       // 手动暂停：线冻结在当前延伸位置
  }
}

function seekFromTrack(event) {
  const rect = event.currentTarget.getBoundingClientRect()
  const ratio = (event.clientX - rect.left) / rect.width
  if (playing.value) togglePlay()
  transitionTo(Math.round(ratio * (years.value.length - 1)))
}

async function load() {
  loading.value = true
  try {
    const data = await getTrend({
      conferences: conferences.value.join(','),
      top_n: topN.value,
    })
    years.value = data.years
    xMin.value = data.years[0] ?? 2022
    xMax.value = data.years[data.years.length - 1] ?? 2026

    // 聚合每词每年：同一年多会议 heat 求和，会议明细随行（tooltip 用）
    linesData = (data.series || []).map((s, si) => {
      const byYear = {}
      for (const d of s.data) {
        byYear[d.year] = byYear[d.year] || { total: 0, confs: [] }
        byYear[d.year].total += d.heat
        byYear[d.year].confs.push({ conference: d.conference, freq: d.freq, heat: d.heat })
      }
      const points = Object.keys(byYear).map(Number).sort((a, b) => a - b)
        .map((y) => ({
          year: y,
          value: Number(byYear[y].total.toFixed(1)),
          confs: byYear[y].confs,
        }))
      return { name: s.name, color: PALETTE[si % PALETTE.length], points }
    })

    // Y 轴固定上限：全量数据的最大热度（需求1，不随帧缩放）
    let m = 0
    for (const l of linesData) for (const p of l.points) m = Math.max(m, p.value)
    yMax.value = niceCeil(m)

    frame.value = years.value.length ? years.value.length - 1 : 0
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
  cancelScan()
  chart?.dispose()
  chart = null
})
watch([conferences, topN], load)
watch(loading, (v) => {
  if (!v) startChart()          // 新语料加载完成：固定坐标轴并从左往右生长
})
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
        <el-select v-model="topN" size="small" style="width: 90px">
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
