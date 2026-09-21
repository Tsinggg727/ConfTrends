<script setup>
/**
 * ① 首页 · 热门方向总览（原型①）。
 * 功能3：Top10 热门方向榜单（热度 = 词频 × 年份增长率）。
 * 图谱 / 搜索框 / 相关论文抽屉属功能4，后续接入。
 */
import { onMounted, ref } from 'vue'

import { getHealth } from '@/api/meta'
import { listPapers } from '@/api/paper'
import { useGlobalStore } from '@/stores/globalStore'
import TopKeywordsCard from '@/components/home/TopKeywordsCard.vue'

const globalStore = useGlobalStore()

const health = ref(null)
const paperCount = ref(null)
const error = ref('')
const loading = ref(true)

onMounted(async () => {
  try {
    const [h, papers] = await Promise.all([getHealth(), listPapers({ page: 1, page_size: 1 })])
    health.value = h
    paperCount.value = papers.total
  } catch (e) {
    error.value = e?.message || '无法连接后端'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="home">
    <section class="ct-card hero-card">
      <h1 class="hero-title">顶会热词统计平台</h1>
      <p class="hero-sub">
        CVPR · ICCV · ECCV 三大顶会论文热词一站式统计 ——
        Top10 热门方向、热度走势与论文管理。
      </p>

      <el-skeleton v-if="loading" :rows="2" animated style="margin-top: 20px" />

      <div v-else class="status" :class="{ bad: !!error }">
        <template v-if="error">
          <span>⚠</span>
          <span>后端未连通：{{ error }}</span>
          <code class="ct-num">cd backend &amp;&amp; python app.py</code>
        </template>
        <template v-else>
          <span class="dot" />
          <span>
            后端已连通（{{ health.service }} v{{ health.version }}）｜ SQLite 可读 ｜
            论文 <b class="ct-num">{{ paperCount }}</b> 篇 ｜
            数据更新 <b class="ct-num">{{ globalStore.summary.updated_at?.slice(0, 10) || '—' }}</b>
          </span>
        </template>
      </div>
    </section>

    <TopKeywordsCard />

    <PagePlaceholder
      title="关键词图谱（功能4 预告）"
      desc="节点大小 = 热度、Top1 高亮、全屏与右侧相关论文抽屉 —— 随功能4 接入。"
      ref="系统设计 §5-①"
      :modules="['搜索框 + 热门快捷标签', '关键词图谱 + 全屏', '右侧相关论文抽屉']"
    />
  </div>
</template>

<style scoped>
.home {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.hero-card {
  text-align: center;
  padding: 40px 24px 32px;
}

.hero-title {
  margin: 0;
  font-size: 34px;
  font-weight: 800;
  letter-spacing: -1px;
  background: linear-gradient(135deg, var(--ct-primary), var(--ct-secondary));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.hero-sub {
  margin: 12px 0 0;
  color: var(--ct-text-sub);
  font-size: 14px;
}

.status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: center;
  margin-top: 24px;
  padding: 10px 18px;
  border-radius: 999px;
  background: rgba(16, 185, 129, 0.08);
  color: #047857;
  font-size: 13px;
}
.status.bad {
  background: rgba(239, 68, 68, 0.08);
  color: #b91c1c;
}
.status code {
  background: rgba(15, 23, 42, 0.06);
  padding: 2px 8px;
  border-radius: 6px;
}
.status b {
  color: var(--ct-primary);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ct-success);
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.2);
}
</style>
