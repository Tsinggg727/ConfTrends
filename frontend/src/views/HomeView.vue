<script setup>
/**
 * ① 首页 · 热门方向总览（原型①）。
 * Hero：深空背景全幅铺满 + 英文艺术字标题（Trending 金色衬线斜体渐变）
 *       + 论文库搜索框 + 热门快捷标签（来自 /stats/top，点击跳列表过滤）；
 * 下方为功能3 Top10 榜单（可折叠）与功能4 关键词图谱（可全屏、节点抽屉）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { getTopStats } from '@/api/stats'
import { listPapers } from '@/api/paper'
import { useGlobalStore } from '@/stores/globalStore'
import TopKeywordsCard from '@/components/home/TopKeywordsCard.vue'
import KeywordGraphCard from '@/components/home/KeywordGraphCard.vue'

const router = useRouter()
const globalStore = useGlobalStore()

const paperCount = ref(null)

const searchTerm = ref('')
const hotTags = ref([])

const stats = computed(() => [
  { value: Number(paperCount.value ?? globalStore.summary.paper_count ?? 0).toLocaleString('en-US'), label: '论文总量' },
  { value: Number(globalStore.summary.keyword_count ?? 0).toLocaleString('en-US'), label: '关键词' },
  { value: Number(globalStore.summary.conference_count ?? 3), label: '三大顶会' },
])

/** 搜索框 → 论文列表按题目检索（列表页读取 route.query.q） */
function goSearch() {
  const q = searchTerm.value.trim()
  if (q) router.push({ path: '/papers', query: { q } })
}

/** 热门快捷标签 → 论文列表按关键词过滤 */
function goKeyword(name) {
  router.push({ path: '/papers', query: { keyword: name } })
}

onMounted(async () => {
  try {
    const papers = await listPapers({ page: 1, page_size: 1 })
    paperCount.value = papers.total
  } catch {
    paperCount.value = null        // 后端未启动：统计数字留空
  }
  try {
    const data = await getTopStats({ n: 5 })
    hotTags.value = data.list.map((r) => r.name)
  } catch {
    hotTags.value = []             // 统计未重算时标签留空，不影响首屏
  }
})
</script>

<template>
  <div class="home">
    <section class="hero">
      <div class="hero-inner">
        <div>
          <div class="hero-kicker">CONF TRENDS · 三大顶会数据洞察</div>
          <h1 class="hero-title">
            <span class="art">Trending</span> words of top conferences
          </h1>
          <p class="hero-sub">
            词频 × 年份增长率，量化 CVPR · ICCV · ECCV 三大顶会的研究风向。
          </p>
          <div class="pill">
            <svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
            <input
              v-model="searchTerm"
              placeholder="搜索论文库，如 Diffusion Models Beat GANs"
              @keyup.enter="goSearch"
            />
            <button class="go" @click="goSearch">Search</button>
          </div>
          <div class="stats">
            <div v-for="s in stats" :key="s.label" class="stat">
              <b class="ct-num">{{ s.value }}</b><span>{{ s.label }}</span>
            </div>
          </div>
          <div class="glass-chips">
            <span
              v-for="t in hotTags"
              :key="t"
              class="glass-chip tag-link"
              @click="goKeyword(t)"
            >{{ t }}</span>
          </div>
        </div>
        <div class="hero-right" aria-hidden="true">
          <div class="hero-ring"><div class="hero-core"></div></div>
        </div>
      </div>
    </section>

    <TopKeywordsCard />

    <KeywordGraphCard />
  </div>
</template>

<style scoped>
.home {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  /* 首页整页统一为 p1 深空背景：铺满视口（负边距出血），内容居中 */
  margin: -1.5rem calc(50% - 50vw) 0;
  padding: 1.5rem calc(50vw - 50%) 1.5rem;
  background:
    radial-gradient(50rem 20rem at 85% -10%, rgba(139, 92, 246, 0.35), transparent 60%),
    radial-gradient(40rem 18rem at 8% 110%, rgba(59, 130, 246, 0.28), transparent 60%),
    linear-gradient(160deg, #0B1226 0%, #111A35 55%, #1E1B4B 100%);
}
.home::before {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    linear-gradient(rgba(148, 163, 184, 0.05) 1px, transparent 1px) 0 0 / 2.5rem 2.5rem,
    linear-gradient(90deg, rgba(148, 163, 184, 0.05) 1px, transparent 1px) 0 0 / 2.5rem 2.5rem;
}

/* Hero：撑满第一屏（导航 3.5rem 以下），标题整体下移居中 */
.hero {
  min-height: calc(100vh - 6.5rem);
  display: flex;
  align-items: center;
}
.hero-inner {
  max-width: 80rem;
  margin: 0 auto;
  padding: 1.5rem 1.5rem 0;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 3rem;
}
.hero-kicker {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.8125rem;
  letter-spacing: 0.3em;
  color: #A5B4FC;
}
.hero-kicker::before {
  content: "";
  width: 2rem;
  height: 0.125rem;
  background: #A5B4FC;              /* 与文字同色（视觉反馈） */
}
/* 英文标题：Trending 衬线斜体金色渐变（参考图 Think 的做法），其余冷调浅渐变 */
.hero-title {
  margin: 1.25rem 0 1rem;
  font-size: clamp(1.5rem, 3vw, 2.375rem);
  font-weight: 800;
  letter-spacing: -0.01em;
  line-height: 1.5;                 /* 两行行距拉开（视觉反馈） */
  color: #E0E7FF;
}
/* Trending 独占一行：行内基准再放大一号半（用独立字号而非 em 相对值） */
.hero-title .art {
  display: inline-block;            /* 单行：与后半句同行 */
  font-family: Georgia, "Times New Roman", serif;
  font-style: italic;
  font-weight: 700;
  letter-spacing: 0.01em;
  font-size: clamp(2.125rem, 4.2vw, 3.5rem);   /* Trending 大一号 */
  margin-right: 0.375em;
  background: linear-gradient(100deg, #E3E6F8 10%, #C3CBF0 45%, #9FA9E4 78%, #8A94DB 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  filter: drop-shadow(0 0 1.25rem rgba(159, 169, 228, 0.30));
}
.hero-title .art {
  font-family: Georgia, "Times New Roman", serif;
  font-style: italic;
  font-weight: 700;
  letter-spacing: 0.01em;
  padding-right: 0.15em;
  font-size: 1.2em;                /* Trending 放大（视觉反馈） */
  background: linear-gradient(100deg, #E3E6F8 10%, #C3CBF0 45%, #9FA9E4 78%, #8A94DB 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  filter: drop-shadow(0 0 1.25rem rgba(159, 169, 228, 0.30));
}
.hero-sub {
  margin-top: 3rem;                 /* 标题与副句拉开至少两行（视觉反馈） */
  font-size: 0.8125rem;
  color: #94A3B8;
  white-space: nowrap;          /* 保持一行（约束：副句不折行） */
  overflow: hidden;
}

/* 胶囊搜索框（参考图 @input + Submit 构图） */
.pill {
  margin-top: 1.5rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: min(26rem, 90%);
  padding: 0.375rem 0.375rem 0.375rem 1rem;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.22);
  backdrop-filter: blur(0.75rem);
}
.pill .ic {
  color: #94A3B8;
}
.pill input {
  flex: 1;
  border: none;
  outline: none;
  font: inherit;
  font-size: 0.875rem;
  color: #E0E7FF;
  background: transparent;
  min-width: 0;
}
.pill input::placeholder {
  color: #7C89A6;
}
.pill .go {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 1.125rem;
  border-radius: 999px;
  border: none;
  background: linear-gradient(135deg, var(--ct-primary), var(--ct-secondary));
  color: #fff;
  font-size: 0.8125rem;
  transition: transform 0.2s var(--ease), opacity 0.2s var(--ease);
}
.pill .go:hover {
  transform: translateY(-0.0625rem);
  opacity: 0.9;
}
.stats {
  display: flex;
  gap: 3rem;
  margin-top: 2rem;
  flex-wrap: wrap;
}
.stat b {
  display: block;
  font-size: 2rem;
  font-weight: 800;
  color: #E0E7FF;
  line-height: 1.1;
}
.stat span {
  font-size: 0.75rem;
  color: #94A3B8;
  letter-spacing: 0.15em;
}
.glass-chips {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin-top: 1.5rem;
}
.glass-chip {
  padding: 0.375rem 0.875rem;
  border-radius: 999px;
  font-size: 0.75rem;
  color: #C7D2FE;
  background: rgba(255, 255, 255, 0.10);
  backdrop-filter: blur(0.75rem);
  border: 1px solid rgba(255, 255, 255, 0.22);
}
.tag-link {
  cursor: pointer;
  transition: opacity 0.2s var(--ease), transform 0.2s var(--ease);
}
.tag-link:hover {
  opacity: 0.85;
  transform: translateY(-0.0625rem);
}
.hero-right {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16rem;
  height: 16rem;
  flex-shrink: 0;
}
.hero-ring {
  width: 11rem;
  height: 11rem;
  border-radius: 50%;
  border: 1px solid rgba(165, 180, 252, 0.35);
  border-top-color: var(--ct-accent);
  animation: ring-spin 24s linear infinite;
  position: relative;
  box-shadow: 0 0 4rem rgba(139, 92, 246, 0.35);
}
.hero-ring::after {
  content: "";
  position: absolute;
  inset: 1.5rem;
  border-radius: 50%;
  border: 1px dashed rgba(165, 180, 252, 0.25);
}
.hero-core {
  position: absolute;
  width: 4rem;
  height: 4rem;
  border-radius: 50%;
  background: radial-gradient(circle at 35% 35%, #A5B4FC, #6366F1);
  box-shadow: 0 0 2rem rgba(99, 102, 241, 0.8);
}
@keyframes ring-spin {
  to { transform: rotate(360deg); }
}
@media (max-width: 56rem) {
  .hero-right { display: none; }
  .hero-inner { gap: 1.5rem; }
  .stats { gap: 1.5rem; }
}

/* 深底上的选择框：半透明玻璃 + 浅色文字（视觉反馈：年份单选框不和谐） */
.home :deep(.el-select__wrapper) {
  background-color: rgba(255, 255, 255, 0.08);
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.22) inset;
}
.home :deep(.el-select__placeholder),
.home :deep(.el-select__selected-item) {
  color: #C7D2FE;
}
.home :deep(.el-select__caret) {
  color: #94A3B8;
}

/* ---------- 深底适配：首页范围内的卡片与文字换深色玻璃风 ---------- */
.home :deep(.ct-card),
.home :deep(.metric) {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.10);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25);
}
.home :deep(.ct-card:hover),
.home :deep(.metric:hover) {
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.40);
}
.home :deep(.title) { color: #E0E7FF; }
.home :deep(.title .ic) { color: #A5B4FC; }
.home :deep(.card-sub),
.home :deep(.section-note),
.home :deep(.rank-freq),
.home :deep(.metric span),
.home :deep(.metric small),
.home :deep(.empty) { color: #7C89A6; }
.home :deep(.rank-name) { color: #E0E7FF; }
/* 深底上金属徽章太暗：序号改白色（视觉反馈定稿） */
.home :deep(.ct-card .rank-badge.gold) {
  color: #fff;
  border-color: #e3cd8f;
  background: rgba(229, 200, 140, 0.20);
}
.home :deep(.ct-card .rank-badge.silver) {
  color: #fff;
  border-color: #c6cdd6;
  background: rgba(214, 220, 229, 0.16);
}
.home :deep(.ct-card .rank-badge.bronze) {
  color: #fff;
  border-color: #d2a878;
  background: rgba(206, 164, 118, 0.16);
}
.home :deep(.ct-card .rank-badge.plain) {
  color: #fff;
  border-color: rgba(255, 255, 255, 0.35);
  background: rgba(255, 255, 255, 0.06);
}
.home :deep(.rank-bar) { background: rgba(255, 255, 255, 0.08); }
.home :deep(.rank-fill) {
  background: linear-gradient(90deg, rgba(139, 124, 208, 0.75), rgba(165, 180, 252, 0.65));
}
.home :deep(.rank-heat) { color: #E0E7FF; }
.home :deep(.metric b) {
  background: linear-gradient(92deg, #E0E7FF, #A5B4FC);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.home :deep(.el-button.is-text) { color: #A5B4FC; }
</style>
