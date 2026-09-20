<script setup>
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'

import { useGlobalStore } from '@/stores/globalStore'

const route = useRoute()
const router = useRouter()
const globalStore = useGlobalStore()
const { year, summary } = storeToRefs(globalStore)

/** 导航项，顺序与原型一致 */
const navItems = [
  { key: 'home', label: '首页', to: '/' },
  { key: 'trend', label: '热度走势', to: '/trend' },
  { key: 'papers', label: '论文管理', to: '/papers' },
  { key: 'crawl', label: '爬取 / 导入', to: '/crawl' },
  { key: 'about', label: '关于', to: '/about' },
]

const activeNav = computed(() => route.meta?.navKey || '')

/** 「数据更新：2026-09-20 ｜ 12,000 篇」 */
const dataBadge = computed(() => {
  const { updated_at, paper_count } = summary.value
  const date = updated_at ? String(updated_at).slice(0, 10) : '—'
  const count = Number(paper_count || 0).toLocaleString('en-US')
  return `数据更新：${date} ｜ ${count} 篇`
})

/** 导航栏年份下拉的可选范围 */
const yearOptions = computed(() => {
  const [min, max] = summary.value.year_range || [2022, 2026]
  const list = []
  for (let y = max; y >= min; y -= 1) list.push(y)
  return list.length ? list : [2026, 2025, 2024, 2023, 2022]
})

function goBack() {
  if (window.history.length > 1) router.back()
  else router.push('/')
}

onMounted(() => {
  globalStore.loadSummary()
  // 年份默认落到数据的最新一年
  const [min, max] = summary.value.year_range || []
  if (max) year.value = max
})
</script>

<template>
  <div class="layout">
    <header class="app-header">
      <div class="header-inner">
        <div class="brand" @click="router.push('/')">
          <span class="brand-icon">🎓</span>
          <span class="brand-text">顶会热词 <em>ConfTrends</em></span>
        </div>

        <nav class="nav">
          <button
            v-if="route.meta?.showBack"
            class="nav-back"
            type="button"
            @click="goBack"
          >
            ← {{ route.meta?.backText || '返回' }}
          </button>

          <router-link
            v-for="item in navItems"
            :key="item.key"
            :to="item.to"
            class="nav-link"
            :class="{ active: activeNav === item.key }"
          >
            {{ item.label }}
          </router-link>
        </nav>

        <div class="header-right">
          <el-select
            v-model="year"
            size="small"
            class="year-select"
            @change="globalStore.setYear"
          >
            <el-option v-for="y in yearOptions" :key="y" :label="`年份 ${y}`" :value="y" />
          </el-select>
          <span class="data-badge ct-num">{{ dataBadge }}</span>
        </div>
      </div>
    </header>

    <main class="app-main">
      <router-view />
    </main>

    <footer class="app-footer">
      数据来源：DBLP API / DBLP 数据集 / 会议官网 ｜ 统计口径：热度 = 词频 × 年份增长率 ｜ 仅用于课程教学
    </footer>
  </div>
</template>

<style scoped>
.layout {
  min-height: 100%;
  display: flex;
  flex-direction: column;
}

/* ---------- 顶部固定导航 ---------- */
.app-header {
  position: sticky;
  top: 0;
  z-index: 100;
  background: var(--ct-navy);
  box-shadow: 0 2px 12px rgba(15, 23, 42, 0.18);
}

.header-inner {
  max-width: 1280px;
  margin: 0 auto;
  height: 56px;
  padding: 0 24px;
  display: flex;
  align-items: center;
  gap: 24px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #fff;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
}
.brand-text em {
  font-style: normal;
  font-weight: 500;
  color: #93c5fd;
}

.nav {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1;
}

.nav-link,
.nav-back {
  padding: 6px 14px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #cbd5e1;
  font-size: 14px;
  text-decoration: none;
  cursor: pointer;
  transition: background 0.2s, color 0.2s;
}
.nav-link:hover,
.nav-back:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}
/* 当前页高亮：渐变底取自设计规范 §3.1 */
.nav-link.active {
  background: linear-gradient(135deg, var(--ct-primary), var(--ct-secondary));
  color: #fff;
  font-weight: 600;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.year-select {
  width: 116px;
}

.data-badge {
  font-size: 12px;
  color: #94a3b8;
  white-space: nowrap;
}

/* ---------- 内容区 / 页脚 ---------- */
.app-main {
  flex: 1;
  max-width: 1280px;
  width: 100%;
  margin: 0 auto;
  padding: 24px;
}

.app-footer {
  padding: 16px 24px;
  text-align: center;
  font-size: 12px;
  color: var(--ct-text-sub);
  border-top: 1px solid #e5e7eb;
  background: #fff;
}
</style>
