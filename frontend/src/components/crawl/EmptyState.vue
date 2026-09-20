<script setup>
/**
 * 空状态 —— 设计 §5.1 EmptyState：尚未开始任何爬取时占住进度区/结果区的位置。
 */
defineProps({
  show: { type: Boolean, default: false },
})
</script>

<template>
  <section v-if="show" class="ct-card empty-card">
    <el-empty description="尚未开始爬取，选择上方任一方式导入论文题目" :image-size="88" />
  </section>
</template>

<style scoped>
.empty-card {
  margin-top: 16px;
}
</style>
