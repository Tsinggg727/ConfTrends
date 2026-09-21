<script setup>
/**
 * Top10 热门方向（功能3 / 原型①）—— 与预览稿一致的 HTML 行式榜单。
 * 排名条统一冷调主色系（视觉评审定稿：不再按名次分金银铜色），前三词名
 * 加粗，徽章金银铜低饱和；条形动画 transform: scaleX（合规约束④）。
 * 可折叠（§5.1「Top10 榜单（折叠）」）。
 */
import { computed, onMounted, ref, watch } from 'vue'

import { getTopStats } from '@/api/stats'

const MEDALS = ['gold', 'silver', 'bronze']

const year = ref(null)
const conference = ref('')
const years = ref([])
const loading = ref(true)
const empty = ref(false)
const collapsed = ref(false)
const rows = ref([])

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
    year.value = data.year ?? data.years?.[0] ?? null
    rows.value = data.list
    empty.value = !data.list.length
  } finally {
    loading.value = false
  }
}

function toggleCollapse() {
  collapsed.value = !collapsed.value
}

onMounted(load)
watch([year, conference], load)

const subtitleText = computed(() =>
  `${year.value ?? '—'} 年 · ${conference.value || '三大会议汇总'} · 热度 = 词频 × 年份增长率`)
</script>

<template>
  <section class="ct-card">
    <div class="card-head">
      <h2 class="title">
        <svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M3 21h18"/><rect x="5" y="10" width="3.5" height="8" rx="1"/><rect x="10.25" y="5" width="3.5" height="13" rx="1"/><rect x="15.5" y="13" width="3.5" height="5" rx="1"/></svg>
        Top10 热门方向
      </h2>
      <span class="card-sub">{{ subtitleText }}</span>
      <span class="spacer" />
      <el-select v-model="conference" size="small" style="width: 132px">
        <el-option v-for="o in confOptions" :key="o.value"
                   :label="o.label" :value="o.value" />
      </el-select>
      <el-select v-model="year" size="small" style="width: 96px"
                 :disabled="!years.length">
        <el-option v-for="y in years" :key="y" :label="`${y} 年`" :value="y" />
      </el-select>
      <el-button size="small" text @click="collapsed = !collapsed">
        {{ collapsed ? '展开' : '收起' }}
      </el-button>
    </div>

    <div v-if="empty && !loading" class="empty">
      暂无热度数据 —— 论文入库并重算统计后这里会出现榜单
    </div>

    <div v-else v-loading="loading" class="rank-list">
      <div
        v-for="(r, i) in rows"
        :key="r.keyword_id"
        class="rank-row"
        :style="{ transitionDelay: (i * 40) + 'ms' }"
      >
        <span class="rank-badge" :class="MEDALS[i] || 'plain'">{{ i + 1 }}</span>
        <span class="rank-name" :class="{ top3: i < 3 }">{{ r.name }}</span>
        <div class="rank-bar">
          <div class="rank-fill" :style="{ width: r.heat_norm + '%' }"></div>
        </div>
        <span class="rank-heat ct-num">{{ Math.round(r.heat) }}</span>
        <span class="rank-freq ct-num">{{ r.freq }} 篇</span>
      </div>
    </div>

    <p class="section-note">
      条长 = scope 内归一化热度；排名条统一冷调主色系，前三词名加粗，徽章金银铜低饱和。条形动画用 transform: scaleX（合规约束④）。
    </p>
  </section>
</template>

<style scoped>
.card-head {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  flex-wrap: wrap;
}
.title {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
  font-size: 1rem;
}
.title .ic {
  color: var(--ct-primary);
}
.card-sub {
  font-size: 0.75rem;
  color: var(--ct-text-weak);
}
.spacer {
  flex: 1;
}
.rank-list {
  margin-top: 1rem;
}
.rank-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.625rem 0;
  border-bottom: 1px solid rgba(35, 38, 43, 0.06);
  transition: opacity 0.3s var(--ease, cubic-bezier(0.22, 1, 0.36, 1)),
              transform 0.3s var(--ease, cubic-bezier(0.22, 1, 0.36, 1));
}
.rank-row:last-child {
  border-bottom: none;
}
.rank-row:hover {
  opacity: 0.85;
  transform: translateX(0.125rem);
}
.rank-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.75rem;
  height: 1.5rem;
  border-radius: 0.375rem;
  flex-shrink: 0;
  font-family: Inter, Consolas, monospace;
  font-variant-numeric: tabular-nums;
  font-weight: 700;
  font-size: 0.8125rem;
  border: 1px solid;
}
.rank-badge.gold {
  color: #8f7333;
  border-color: #c9a85c;
  background: linear-gradient(180deg, rgba(230, 200, 130, 0.30), rgba(200, 168, 92, 0.12));
}
.rank-badge.silver {
  color: #64707f;
  border-color: #aeb6c2;
  background: linear-gradient(180deg, rgba(214, 220, 229, 0.38), rgba(180, 189, 201, 0.15));
}
.rank-badge.bronze {
  color: #8a6236;
  border-color: #b08250;
  background: linear-gradient(180deg, rgba(206, 164, 118, 0.28), rgba(166, 124, 80, 0.12));
}
.rank-badge.plain {
  color: var(--ct-text-weak);
  border-color: #e2e8f0;
  background: transparent;
}
.rank-name {
  width: 9rem;
  font-size: 0.875rem;
  font-weight: 400;
  flex-shrink: 0;
}
.rank-name.top3 {
  font-weight: 700;
}
.rank-bar {
  flex: 1;
  height: 1.125rem;
  background: rgba(35, 38, 43, 0.05);
  border-radius: 0.25rem;
  overflow: hidden;
}
.rank-fill {
  height: 100%;
  border-radius: 0.25rem;
  transform: scaleX(0);
  transform-origin: left;
  animation: fill-in 0.9s var(--ease, cubic-bezier(0.22, 1, 0.36, 1)) forwards;
  background: linear-gradient(90deg, rgba(108, 130, 180, 0.50), rgba(139, 124, 200, 0.42));
}
@keyframes fill-in {
  to { transform: scaleX(1); }
}
.rank-heat {
  width: 4.5rem;
  text-align: right;
  font-weight: 600;
  font-size: 0.875rem;
  flex-shrink: 0;
}
.rank-freq {
  width: 5rem;
  text-align: right;
  font-size: 0.75rem;
  color: var(--ct-text-weak);
  flex-shrink: 0;
}
.empty {
  padding: 3rem 0;
  text-align: center;
  font-size: 0.8125rem;
  color: var(--ct-text-sub);
}
.section-note {
  margin: 0.625rem 0 0;
  font-size: 0.75rem;
  color: var(--ct-text-weak);
}
</style>
