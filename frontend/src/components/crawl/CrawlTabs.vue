<script setup>
/**
 * 三个入口 Tab —— 设计 §5.1。
 * el-tab-pane 默认不销毁切走的面板（非 lazy），各 Tab 已填的内容自然保留，
 * 满足 §5.3「切 Tab 不丢输入」。
 */
defineProps({
  active: { type: String, required: true },
})
defineEmits(['update:active'])
</script>

<template>
  <el-tabs
    :model-value="active"
    class="crawl-tabs"
    @update:model-value="$emit('update:active', $event)"
  >
    <el-tab-pane label="① 单个题目" name="single">
      <slot name="single" />
    </el-tab-pane>
    <el-tab-pane label="② 批量题目" name="batch">
      <slot name="batch" />
    </el-tab-pane>
    <el-tab-pane label="③ BibTeX / 整届" name="bibtex">
      <slot name="bibtex" />
    </el-tab-pane>
  </el-tabs>
</template>

<style scoped>
.crawl-tabs :deep(.el-tabs__item) {
  font-size: 14px;
}
</style>
