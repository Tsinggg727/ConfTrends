<script setup>
import PagePlaceholder from '@/components/PagePlaceholder.vue'
</script>

<template>
  <PagePlaceholder
    title="④ 论文爬取 / 导入"
    desc="📌 数据来源说明前置（合规）+ 单条输入 + 批量导入（文件 / 粘贴列表）+ 进度条（80% 正在爬取第 4/5 篇）+ 成功行三字段 / 失败行重试 + 底部批量操作。"
    ref="系统设计 §5-④"
    :modules="[
      'SourceNotice 来源说明前置',
      'SingleCrawlForm 单条爬取',
      'BatchImportPanel 批量导入',
      '进度条（轮询任务）',
      'CrawlResultList 结果列表',
      '重试失败项 / 全部入库',
    ]"
  />
</template>
