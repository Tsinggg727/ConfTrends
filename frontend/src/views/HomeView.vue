<script setup>
/**
 * ① 首页 · 热门方向总览
 *
 * 骨架阶段只做一件事：显示 Hello，并验证「前端 → Vite 代理 → Flask → SQLite」
 * 整条链路是通的。完整实现见系统设计 §5-①。
 */
import { onMounted, ref } from 'vue'

import { getHealth } from '@/api/meta'
import { listPapers } from '@/api/paper'
import { useGlobalStore } from '@/stores/globalStore'
import PagePlaceholder from '@/components/PagePlaceholder.vue'

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
    <section class="ct-card hello-card">
      <h1 class="hello">Hello</h1>
      <p class="hello-sub">顶会热词统计平台骨架已就绪 —— Vue 3 + Vite + Element Plus + ECharts ／ Flask + SQLite</p>

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

    <PagePlaceholder
      title="首页 · 热门方向总览"
      desc="骨架完成后，本页按设计文档实现 Top10 榜单、关键词图谱（节点大小=热度、Top1 高亮）、搜索框与热门快捷标签、右侧抽屉。"
      ref="系统设计 §5-①"
      :modules="['Hero 统计条', '搜索框 + 热门快捷标签', 'Top10 榜单（折叠）', '关键词图谱 + 全屏', '右侧相关论文抽屉']"
    />
  </div>
</template>

<style scoped>
.home {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.hello-card {
  text-align: center;
  padding: 48px 24px;
}

.hello {
  margin: 0;
  font-size: 56px;
  font-weight: 800;
  letter-spacing: -1px;
  background: linear-gradient(135deg, var(--ct-primary), var(--ct-secondary));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.hello-sub {
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
