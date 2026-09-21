<script setup>
/**
 * 新增 / 编辑论文弹窗 —— 原型③ 的 PaperFormDialog。
 * paper 为 null 是新增（source='manual'），否则是编辑；
 * 后端对题目判重 / 年份越界 / 会议不存在会返回 4xx，提示由拦截器统一弹。
 */
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { createPaper, updatePaper } from '@/api/paper'
import { useUnitsStore } from '@/stores/unitsStore'

const unitsStore = useUnitsStore()

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  /** null = 新增；对象 = 编辑（只取可编辑字段） */
  paper: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'saved'])

const isEdit = computed(() => !!props.paper)
const saving = ref(false)

const form = reactive({
  title: '',
  conference_code: '',
  year: undefined,
  authors: '',
  abstract: '',
  url: '',
  doi: '',
})

watch(() => props.modelValue, (open) => {
  if (!open) return
  // 弹窗打开时确保日历在手（新增/编辑都要选会议）
  if (!unitsStore.units.length) unitsStore.load()
  Object.assign(form, {
    title: props.paper?.title || '',
    conference_code: props.paper?.conference?.code || '',
    year: props.paper?.year || undefined,
    authors: props.paper?.authors || '',
    abstract: props.paper?.abstract || '',
    url: props.paper?.url || '',
    doi: props.paper?.doi || '',
  })
})

async function save() {
  if (!form.title.trim()) {
    ElMessage.warning('请输入论文题目')
    return
  }
  saving.value = true
  try {
    if (isEdit.value) {
      await updatePaper(props.paper.id, { ...form })
      ElMessage.success('已保存')
    } else {
      await createPaper({ ...form })
      ElMessage.success('已新增')
    }
    emit('update:modelValue', false)
    emit('saved')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="isEdit ? '编辑论文' : '新增论文'"
    width="560px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-form label-width="72px" label-position="left">
      <el-form-item label="题目" required>
        <el-input v-model="form.title" maxlength="500" show-word-limit
                  placeholder="论文完整题目" />
      </el-form-item>
      <el-form-item label="会议">
        <el-select v-model="form.conference_code" placeholder="不指定" clearable
                   style="width: 160px">
        <el-option v-for="code in unitsStore.conferenceCodes" :key="code"
                   :label="code" :value="code" />
        </el-select>
      </el-form-item>
      <el-form-item label="年份">
        <el-input-number v-model="form.year" :min="2022" :max="2026"
                         :controls="false" style="width: 120px" />
      </el-form-item>
      <el-form-item label="作者">
        <el-input v-model="form.authors" placeholder="逗号分隔" />
      </el-form-item>
      <el-form-item label="摘要">
        <el-input v-model="form.abstract" type="textarea" :rows="4" />
      </el-form-item>
      <el-form-item label="原文链接">
        <el-input v-model="form.url" placeholder="https://..." />
      </el-form-item>
      <el-form-item label="DOI">
        <el-input v-model="form.doi" />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>
