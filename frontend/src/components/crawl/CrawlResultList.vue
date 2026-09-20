<script setup>
/**
 * 爬取结果列表 —— 设计 §5.1 CrawlResultList。
 * 筛选 [全部/成功/失败] 与分页都走后端 GET /tasks/{id}/items（§5.3：
 * 2,700 条全量拉到前端会卡）；轮询期间由 store 增量插入新行，行以 seq
 * 为 key，已有行不重渲染，滚动位置不丢。
 */
import { computed } from 'vue'

import { useCrawlStore } from '@/stores/crawlStore'
import ResultRow from './ResultRow.vue'

const store = useCrawlStore()

const running = computed(() => store.isRunning)

const filters = [
  { value: 'all', label: '全部' },
  { value: 'success', label: '成功' },
  { value: 'failed', label: '失败' },
]
</script>

<template>
  <section v-if="store.task" class="ct-card list-card">
    <div class="head">
      <h2 class="list-title">爬取结果</h2>
      <el-radio-group
        :model-value="store.filter"
        size="small"
        @update:model-value="store.setFilter"
      >
        <el-radio-button v-for="f in filters" :key="f.value" :value="f.value">
          {{ f.label }}
        </el-radio-button>
      </el-radio-group>
      <span class="ct-num total">共 {{ store.total }} 条</span>
    </div>

    <div v-if="store.visibleRows.length" class="rows">
      <ResultRow
        v-for="row in store.visibleRows"
        :key="row.seq"
        :row="row"
        @ignore="store.ignoreRow"
      />
    </div>

    <div v-else class="empty-mini">
      <template v-if="running && store.total === 0">正在抓取第一批结果…</template>
      <template v-else>筛选条件下暂无结果</template>
      <el-button
        v-if="store.filter !== 'all'"
        link
        type="primary"
        @click="store.setFilter('all')"
      >
        查看全部
      </el-button>
    </div>

    <el-pagination
      v-if="store.total > store.visibleRows.length || store.page > 1"
      class="pager"
      layout="prev, pager, next, total"
      :total="store.total"
      :page-size="20"
      :current-page="store.page"
      @current-change="store.setPage"
    />
  </section>
</template>

<style scoped>
.list-card {
  margin-top: 16px;
}
.head {
  display: flex;
  align-items: center;
  gap: 16px;
}
.list-title {
  margin: 0;
  font-size: 15px;
}
.total {
  margin-left: auto;
  font-size: 13px;
  color: var(--ct-text-sub);
}
.rows {
  margin-top: 6px;
}
.empty-mini {
  padding: 28px 0;
  text-align: center;
  font-size: 13px;
  color: var(--ct-text-sub);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}
.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
</style>
