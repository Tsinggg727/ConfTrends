<script setup>
/**
 * 论文列表管理 —— 功能2 / 原型③。
 * 合并搜索框（[精确 ▾] + 输入 + 查询）+ 斑马纹表格 + 分页 + 新增/编辑弹窗
 * + 删除二次确认 + 两类空状态（带关键词空结果给「联网爬取兜底」）。
 *
 * 兜底的语义：查询无结果时由**用户显式**点 [🌐 联网爬取并返回]，
 * 走功能1 的 POST /papers/crawl（auto_commit=true，直接写库）——
 * 不在 GET /papers 上做隐式爬取副作用。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { crawlSingle } from '@/api/crawl'
import { deletePaper, listPapers } from '@/api/paper'
import { useGlobalStore } from '@/stores/globalStore'
import PaperFormDialog from '@/components/papers/PaperFormDialog.vue'

const route = useRoute()
const router = useRouter()
const globalStore = useGlobalStore()

const query = reactive({
  q: String(route.query.q || ''),
  mode: 'fuzzy',
  keyword: String(route.query.keyword || ''),
  page: 1,
  pageSize: 10,
})
const list = ref([])
const total = ref(0)
const loading = ref(false)
const dialogOpen = ref(false)
const editing = ref(null)               // null=新增；对象=编辑

const YEAR_OPTIONS = computed(() => {
  const [min, max] = globalStore.summary.year_range || [2022, 2026]
  const years = []
  for (let y = max; y >= min; y -= 1) years.push(y)
  return years
})

/** 是否处于「有检索词但没查到」的空态 —— 兜底按钮只在这种情况出现 */
const missWithQuery = computed(() =>
  !loading.value && total.value === 0 && (query.q.trim() || query.keyword))

async function load() {
  loading.value = true
  try {
    const data = await listPapers({
      q: query.q.trim() || undefined,
      mode: query.mode,
      keyword: query.keyword || undefined,
      page: query.page,
      page_size: query.pageSize,
    })
    list.value = data.list
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function search() {
  query.page = 1
  load()
}

function clearFilters() {
  query.q = ''
  query.keyword = ''
  query.page = 1
  load()
}

function onPageChange(page) {
  query.page = page
  load()
}

function onSizeChange(size) {
  query.pageSize = size
  query.page = 1
  load()
}

function openCreate() {
  editing.value = null
  dialogOpen.value = true
}

function openEdit(row) {
  editing.value = row
  dialogOpen.value = true
}

async function removeRow(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${row.title}」？删除后可在恢复前通过接口找回，热词统计会随之变化。`,
      '删除论文',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  await deletePaper(row.id)
  ElMessage.success('已删除')
  load()
}

/** 兜底：按检索词当题目去爬，auto_commit=true 直接入库，回来刷新列表 */
const crawling = ref(false)
async function crawlFallback() {
  crawling.value = true
  try {
    const data = await crawlSingle({ title: query.q.trim(), auto_commit: true })
    if (data.status === 'success') {
      ElMessage.success(`已爬取并入库：「${data.paper.title}」`)
      clearFilters()
    } else {
      ElMessage.warning(data.fail_message || '联网爬取未命中，请换用官网完整标题')
    }
  } finally {
    crawling.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="paper-list-view">
    <div class="page-head">
      <h1 class="page-title">论文列表管理</h1>
      <span class="ct-num page-sub">共 {{ total }} 篇</span>
    </div>

    <section class="ct-card">
      <!-- 合并搜索框 + 新增 -->
      <div class="toolbar">
        <el-select v-model="query.mode" class="mode-select" @change="search">
          <el-option label="精确" value="exact" />
          <el-option label="模糊" value="fuzzy" />
        </el-select>
        <el-input
          v-model="query.q"
          class="search-input"
          :placeholder="query.mode === 'exact'
            ? '按题目精确检索（子串匹配）'
            : '题目 / 编号 / 关键词'"
          clearable
          @keyup.enter="search"
        />
        <el-button type="primary" @click="search">查询</el-button>
        <el-button
          v-if="query.keyword"
          size="small"
          closable
          type="info"
          effect="plain"
          @click="query.keyword = ''; search()"
        >
          关键词：{{ query.keyword }}
        </el-button>

        <div class="spacer" />
        <el-button @click="openCreate">＋ 新增</el-button>
      </div>

      <!-- 结果表格 -->
      <el-table
        v-if="total || loading"
        v-loading="loading"
        :data="list"
        stripe
        class="table"
      >
        <el-table-column label="题目" min-width="320">
          <template #default="{ row }">
            <router-link
              class="title-link"
              :to="`/papers/${row.id}`"
            >
              {{ row.title }}
            </router-link>
          </template>
        </el-table-column>
        <el-table-column label="会议" width="110">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.conference?.code || '—' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="year" label="年份" width="90" />
        <el-table-column label="关键词" min-width="220">
          <template #default="{ row }">
            <el-tag
              v-for="kw in row.keywords.slice(0, 4)"
              :key="kw"
              size="small"
              effect="plain"
              class="kw-tag"
              @click="query.keyword = kw; search()"
            >
              {{ kw }}
            </el-tag>
            <span v-if="!row.keywords.length" class="no-kw">暂无</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary"
                       @click="router.push(`/papers/${row.id}`)">查看</el-button>
            <el-button size="small" text type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" text type="danger" @click="removeRow(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <el-pagination
        v-if="total > query.pageSize"
        class="pager"
        layout="total, sizes, prev, pager, next"
        :total="total"
        :page-sizes="[10, 20, 50]"
        :page-size="query.pageSize"
        :current-page="query.page"
        @current-change="onPageChange"
        @size-change="onSizeChange"
      />

      <!-- 空态一：有检索词但没查到 → 联网爬取兜底（原型③） -->
      <div v-else-if="missWithQuery" class="empty miss">
        <div class="miss-title">⚠ 未找到「{{ query.q || query.keyword }}」</div>
        <p class="miss-sub">
          论文库中没有匹配的记录。可以按这个题目联网爬取（CVF / ECVA），
          抓回摘要、原文链接后直接入库并返回。
        </p>
        <div class="miss-actions">
          <el-button type="primary" :loading="crawling" @click="crawlFallback">
            🌐 联网爬取并返回
          </el-button>
          <el-button @click="clearFilters">取消</el-button>
        </div>
        <p class="miss-hint">联网爬取按限速抓取，约 5–20 秒；未限定会议年份时会慢一些</p>
      </div>

      <!-- 空态二：库里没数据 → 去爬取导入 -->
      <div v-else class="empty">
        <el-empty description="论文库还是空的">
          <el-button type="primary" @click="router.push('/crawl')">
            前往爬取 / 导入
          </el-button>
        </el-empty>
      </div>
    </section>

    <PaperFormDialog
      v-model="dialogOpen"
      :paper="editing"
      @saved="load"
    />
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: baseline;
  gap: 14px;
}
.page-title {
  font-size: 22px;
  margin: 0;
}
.page-sub {
  font-size: 13px;
  color: var(--ct-text-sub);
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.mode-select {
  width: 96px;
}
.search-input {
  max-width: 420px;
}
.spacer {
  flex: 1;
}
.table {
  width: 100%;
}
.title-link {
  color: var(--ct-text);
  text-decoration: none;
  font-weight: 500;
}
.title-link:hover {
  color: var(--ct-primary);
}
.kw-tag {
  margin-right: 6px;
  cursor: pointer;
}
.kw-tag:hover {
  color: var(--ct-primary);
  border-color: var(--ct-primary);
}
.no-kw {
  font-size: 12px;
  color: #9aa4b2;
}
.pager {
  margin-top: 14px;
  justify-content: flex-end;
}
.empty {
  padding: 30px 0;
}
.miss {
  text-align: center;
  padding: 46px 0;
}
.miss-title {
  font-size: 17px;
  font-weight: 600;
}
.miss-sub {
  max-width: 460px;
  margin: 10px auto;
  font-size: 13px;
  color: var(--ct-text-sub);
  line-height: 1.8;
}
.miss-actions {
  display: flex;
  justify-content: center;
  gap: 12px;
  margin-top: 6px;
}
.miss-hint {
  margin-top: 14px;
  font-size: 12px;
  color: #9aa4b2;
}
</style>
