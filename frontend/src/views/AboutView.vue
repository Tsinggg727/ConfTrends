<script setup>
import PagePlaceholder from '@/components/PagePlaceholder.vue'
</script>

<template>
  <PagePlaceholder
    title="⑥ 关于 / 了解更多"
    desc="三大顶会卡片（可展开：简介 / 周期 / 规模 / 官网链接）+ 合并的「数据说明」区块（统计口径 + 数据来源 + 范围与用途）。"
    ref="系统设计 §5-⑥"
    :modules="[
      'ConferenceCard ×3（CVPR / ICCV / ECCV）',
      'DataStatement 数据说明',
      '统计口径：热度 = 词频 × 年份增长率',
    ]"
  />
</template>
