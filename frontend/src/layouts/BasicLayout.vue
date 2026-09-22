<script setup>
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'

import { useGlobalStore } from '@/stores/globalStore'
import { useCrawlStore } from '@/stores/crawlStore'

const route = useRoute()
const router = useRouter()
const globalStore = useGlobalStore()
const crawlStore = useCrawlStore()
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
  // 导航角标：有没有任务在跑，问历史接口最省事（不启动轮询）
  crawlStore.loadHistory()
})
</script>

<template>
  <div class="layout">
    <header class="app-header">
      <div class="header-inner">
        <div class="brand" @click="router.push('/')">
          <!-- 学位帽 SVG + 品牌渐变（#3B82F6 → #8B5CF6），替代 emoji -->
          <svg class="brand-icon" viewBox="0 0 24 24" aria-hidden="true">
            <defs>
              <linearGradient id="brand-grad" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stop-color="#3B82F6" />
                <stop offset="1" stop-color="#8B5CF6" />
              </linearGradient>
            </defs>
            <path d="M12 3 2.5 7.5 12 12l9.5-4.5L12 3z" fill="url(#brand-grad)" />
            <path d="M6.5 10.2v4c0 1.6 2.5 2.9 5.5 2.9s5.5-1.3 5.5-2.9v-4"
                  fill="none" stroke="url(#brand-grad)" stroke-width="1.7"
                  stroke-linecap="round" />
            <path d="M21.5 8.2v4.8" fill="none" stroke="url(#brand-grad)"
                  stroke-width="1.7" stroke-linecap="round" />
          </svg>
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
            <!-- 后台有爬取任务在跑时给「爬取 / 导入」加小圆点角标（§5.3） -->
            <span
              v-if="item.key === 'crawl' && crawlStore.navBadge"
              class="run-dot"
            />
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
      数据来源：CVF Open Access（CVPR / ICCV）· ECVA（ECCV）· Semantic Scholar（兜底）｜
      统计口径：热度 = 词频 × 年份增长率 ｜ 仅用于课程教学
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
  /* 深蓝黑 → 深蓝横向渐变（问题4：导航栏不再纯色） */
  background: linear-gradient(90deg, #0A111F 0%, #0F172A 52%, #16243F 100%);
  box-shadow: 0 2px 12px rgba(15, 23, 42, 0.18);
}
/* 底部 1px 极淡主色渐变细线作为分隔 */
.app-header::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent,
    rgba(76, 111, 182, 0.55) 28%, rgba(139, 124, 208, 0.45) 72%, transparent);
  pointer-events: none;
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
.brand-icon {
  width: 24px;
  height: 24px;
  flex-shrink: 0;
}
.brand-text em {
  font-style: normal;
  color: #A78BFA;               /* 淡紫：与首页 Hero 淡紫同族 */
  font-weight: 500;
  font-size: 12px;
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
  transition: color 0.2s, opacity 0.2s;
}
/* 悬停：文字微亮，不加底色方框 */
.nav-link:hover,
.nav-back:hover {
  color: #F1F5F9;
}
/* 选中：只做文字高亮 —— 淡紫 + 2px 短下划线，无边框无底色块 */
.nav-link.active {
  color: #A78BFA;
  font-weight: 600;
}
.nav-link.active::after {
  content: "";
  position: absolute;
  left: 14px;
  right: 14px;
  bottom: -1px;
  height: 2px;
  border-radius: 1px;
  background: #A78BFA;
  opacity: 0.75;
}

/* 后台任务运行中的小圆点角标 */
.nav-link {
  position: relative;
}
.run-dot {
  position: absolute;
  top: 2px;
  right: 4px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ct-accent);
  box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.25);
  animation: dot-pulse 1.6s ease-in-out infinite;
}
@keyframes dot-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
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
