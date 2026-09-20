<script setup>
import { useRoute } from 'vue-router'

import PagePlaceholder from '@/components/PagePlaceholder.vue'

const route = useRoute()
</script>

<template>
  <PagePlaceholder
    :title="`⑤ 论文详情（id = ${route.params.id}）`"
    desc="左右两栏：左为主（题目 / 可点击关键词标签 / 摘要折叠），右为辅（会议年份 / 原文链接 / 相关论文）。相关论文点击继续跳详情，形成浏览闭环。"
    ref="系统设计 §5-⑤"
    :modules="[
      '左栏：题目 + 关键词标签 + 摘要折叠',
      '右栏：会议年份 + OpenReview / DBLP 外链',
      'RelatedPaperList 相关论文闭环',
    ]"
  />
</template>
