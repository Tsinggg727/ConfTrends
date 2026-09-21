<script setup>
/**
 * 数据来源与合规说明 —— 设计 §5.1：页面顶部前置、不可折叠。
 * 合规声明（限速、不存 PDF、仅教学用途）必须出现在用户提交任何抓取之前。
 */
const items = [
  '论文清单：CVF Open Access（CVPR / ICCV）· ECVA（ECCV）',
  '摘要来源：两站论文详情页内嵌摘要（Semantic Scholar 仅作兜底）',
  '范围：CVPR / ICCV / ECCV，2022 年至今（ECCV 实际为 2022 / 2024）',
  '抓取限速 ≤ 1 req/s，仅抓元数据与摘要，不下载 PDF；仅用于课程教学',
]
</script>

<template>
  <div class="source-notice">
    <span class="notice-icon"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21s-7-5.5-7-11a7 7 0 0 1 14 0c0 5.5-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/></svg></span>
    <div class="notice-body">
      <div class="notice-title">数据来源与合规说明</div>
      <ul class="notice-list">
        <li v-for="text in items" :key="text">{{ text }}</li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.source-notice {
  display: flex;
  gap: 12px;
  padding: 14px 18px;
  border-radius: var(--ct-radius);
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1e40af;
}
.notice-icon {
  display: inline-flex;
  color: #1d4ed8;
}
.notice-icon .ic {
  width: 1.25rem;
  height: 1.25rem;
}
.notice-title {
  font-weight: 600;
  font-size: 13px;
}
.notice-list {
  margin: 4px 0 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.9;
  color: #1d4ed8;
}
</style>
