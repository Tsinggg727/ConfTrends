<script setup>
/**
 * 骨架阶段的页面占位块。
 * 每个未实现的页面用它标注「规划中的模块 + 对应设计文档章节」，
 * 避免打开是纯空白页，也方便对着设计文档逐个替换。
 */
defineProps({
  title: { type: String, required: true },
  desc: { type: String, default: '' },
  ref: { type: String, default: '' },
  modules: { type: Array, default: () => [] },
})
</script>

<template>
  <section class="ct-card">
    <div class="ct-placeholder">
      <div class="ct-ph-title">{{ title }}</div>
      <p v-if="desc" class="ct-ph-desc">{{ desc }}</p>
      <el-tag v-if="ref" type="info" effect="plain" size="small">{{ ref }}</el-tag>

      <div v-if="modules.length" class="ct-ph-modules">
        <el-tag
          v-for="m in modules"
          :key="m"
          size="small"
          effect="plain"
        >
          {{ m }}
        </el-tag>
      </div>
    </div>
  </section>
</template>

<style scoped>
.ct-ph-desc {
  margin: 0;
  max-width: 640px;
  text-align: center;
  font-size: 14px;
}
.ct-ph-modules {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-top: 8px;
  max-width: 720px;
}
</style>
