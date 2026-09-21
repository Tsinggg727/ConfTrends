<script setup>
/**
 * 爬取 / 导入页 —— 设计 §5.2 自上而下：
 * SourceNotice → CrawlTabs（三个表单）→ TaskProgress → CrawlResultList
 * → TaskFooter → TaskHistory（无任务时 EmptyState 占位）。
 *
 * 页面挂载即恢复任务：localStorage 里有未完成的 task_id 就接着轮询 ——
 * 中途关页面再回来，进度不丢（§5.3）。
 */
import { onMounted, onUnmounted, ref } from 'vue'

import { useCrawlStore } from '@/stores/crawlStore'
import CrawlTabs from '@/components/crawl/CrawlTabs.vue'
import SingleCrawlForm from '@/components/crawl/SingleCrawlForm.vue'
import BatchTitlePanel from '@/components/crawl/BatchTitlePanel.vue'
import BibtexUploadPanel from '@/components/crawl/BibtexUploadPanel.vue'
import TaskProgress from '@/components/crawl/TaskProgress.vue'
import CrawlResultList from '@/components/crawl/CrawlResultList.vue'
import TaskFooter from '@/components/crawl/TaskFooter.vue'
import TaskHistory from '@/components/crawl/TaskHistory.vue'
import EmptyState from '@/components/crawl/EmptyState.vue'

const store = useCrawlStore()
const activeTab = ref('single')

onMounted(() => {
  store.restore()
})

// 离开页面不停止轮询（§5.3：大批量任务允许离开本页，导航角标提示）；
// 组件销毁只清掉本页的视图状态引用，定时器归 store 管，跨路由存活。
onUnmounted(() => {})
</script>

<template>
  <div class="crawl-view">
    <section class="ct-card tabs-card">
      <CrawlTabs v-model:active="activeTab">
        <template #single>
          <SingleCrawlForm />
        </template>
        <template #batch>
          <BatchTitlePanel />
        </template>
        <template #bibtex>
          <BibtexUploadPanel />
        </template>
      </CrawlTabs>
    </section>

    <TaskProgress />
    <CrawlResultList />
    <TaskFooter />
    <EmptyState :show="!store.task" />
    <TaskHistory />
  </div>
</template>

<style scoped>
.tabs-card {
  margin-top: 16px;
}
</style>
