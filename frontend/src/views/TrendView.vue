<script setup>
import PagePlaceholder from '@/components/PagePlaceholder.vue'
</script>

<template>
  <PagePlaceholder
    title="② 热度走势对比"
    desc="筛选栏（年份范围 / 会议多选 / Top N）+ 折线图逐年生长动画 + 年份进度条 + 播放暂停居中、导出 GIF 右置 + 可点击图例。"
    ref="系统设计 §5-②"
    :modules="[
      'FilterBar 筛选栏',
      'TrendLineChart 折线图',
      'YearProgress 年份进度条',
      'PlayerControl 播放 / 导出 GIF',
      '可点击图例',
    ]"
  />
</template>
