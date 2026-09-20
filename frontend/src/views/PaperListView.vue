<script setup>
import PagePlaceholder from '@/components/PagePlaceholder.vue'
</script>

<template>
  <PagePlaceholder
    title="③ 论文列表管理"
    desc="合并搜索框（[精确 ▾] 模式切换）+ 操作栏（新增/批量导入左置、删除选中右置弱化）+ 斑马纹表格 + 分页（含每页条数）+ 两类空状态 + 删除二次确认。"
    ref="系统设计 §5-③"
    :modules="[
      'SearchBar 合并搜索框',
      'PaperTable 表格 + 多选',
      'PaperFormDialog 新增 / 编辑',
      'ConfirmDialog 删除确认',
      'EmptyState 空状态（无结果 / 空库）',
      '分页器',
    ]"
  />
</template>
