<script setup>
/**
 * 底部批量操作 —— 设计 §5.1 TaskFooter。
 * [重试失败项] 生成新任务的设计在 §5.3，后端 /retry 属步骤 7，先禁用占位；
 * [全部入库] 仅暂存模式显示，边爬边入库换成静态提示（§5.3）；
 * [取消任务] 二次确认，说明已完成的篇数会保留。
 */
import { computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { useCrawlStore } from '@/stores/crawlStore'

const store = useCrawlStore()

const hasFailures = computed(() => (store.task?.failed ?? 0) > 0)
const showFooter = computed(() =>
  store.task && (store.isStaged || hasFailures.value || store.canCancel))

async function commitAll() {
  const counts = await store.commit()
  ElMessage.success(
    `成功入库 ${counts.inserted + counts.updated} 篇`
    + `（新增 ${counts.inserted} / 补全 ${counts.updated} / 跳过重复 ${counts.skipped_dup}）`,
  )
}

async function cancelTask() {
  const kept = store.task?.success ?? 0
  try {
    await ElMessageBox.confirm(
      `已完成的 ${kept} 篇会保留，剩余未处理的将停止抓取。确定取消？`,
      '取消任务',
      { confirmButtonText: '确定取消', cancelButtonText: '再想想', type: 'warning' },
    )
  } catch {
    return
  }
  await store.cancel()
  ElMessage.info('已请求取消，当前这一篇完成后停手')
}
</script>

<template>
  <div v-if="showFooter" class="task-footer">
    <div class="left">
      <el-tooltip content="失败重试将在步骤 7 接入" placement="top">
        <span>
          <el-button :disabled="!hasFailures">重试失败项</el-button>
        </span>
      </el-tooltip>

      <el-button v-if="store.isStaged" type="primary" @click="commitAll">
        全部入库
      </el-button>
      <span v-else class="committed ct-num">
        已实时入库 {{ store.task?.success ?? 0 }} 篇
      </span>
    </div>

    <el-button v-if="store.canCancel" type="danger" plain @click="cancelTask">
      ✕ 取消任务
    </el-button>
  </div>
</template>

<style scoped>
.task-footer {
  margin-top: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.committed {
  font-size: 13px;
  color: var(--ct-success);
}
</style>
