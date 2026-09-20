<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <section class="ct-card">
    <div class="ct-placeholder">
      <el-result icon="warning" title="404" sub-title="页面不存在或已被移动">
        <template #extra>
          <el-button type="primary" @click="router.push('/')">返回首页</el-button>
        </template>
      </el-result>
    </div>
  </section>
</template>
