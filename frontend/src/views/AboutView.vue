<script setup>
/**
 * ⑥ 关于 / 了解更多（原型⑥ / 系统设计 §5-⑥）。
 * ConferenceCard ×3：CVPR / ICCV / ECCV，点击标题栏展开
 * 「简介 / 周期 / 规模 / 官网链接」（el-collapse-transition 过渡）；
 * DataStatement：统计口径 + 数据来源 + 范围与用途合并展示。
 *
 * 卡片内容全部来自 GET /conferences，不在前端硬编码 —— 改文案只改库；
 * 请求失败降级为内置默认文案（degraded 提示），页面不空白。
 */
import { onMounted, reactive, ref } from 'vue'

import { getConferences } from '@/api/conference'

const FALLBACK = [
  {
    code: 'CVPR', name: 'CVPR', cycle: '每年一届', scale: '约 3000 篇录用',
    official_url: 'https://cvpr.thecvf.com/',
    intro: 'IEEE/CVF Conference on Computer Vision and Pattern Recognition，' +
      '计算机视觉领域规模最大、影响力最高的顶级会议，论文涵盖图像识别、生成模型、三维重建等方向。',
  },
  {
    code: 'ICCV', name: 'ICCV', cycle: '两年一届（奇数年）', scale: '约 2000 篇录用',
    official_url: 'https://iccv.thecvf.com/',
    intro: 'IEEE/CVF International Conference on Computer Vision，' +
      '与 CVPR 并列的计算机视觉顶级会议，每两年举办一次，录取率通常低于 CVPR。',
  },
  {
    code: 'ECCV', name: 'ECCV', cycle: '两年一届（偶数年）', scale: '约 2000 篇录用',
    official_url: 'https://eccv.ecva.net/',
    intro: 'European Conference on Computer Vision，' +
      '欧洲计算机视觉会议，与 CVPR、ICCV 并称三大顶会，偶数年举办。',
  },
]

const conferences = ref(FALLBACK)
const loading = ref(true)
const degraded = ref(false)              // true = 后端不可达，正在用内置文案
const expanded = reactive(new Set(['CVPR']))   // 默认展开第一张

function toggle(code) {
  // expanded 是 reactive Set：原位增删（不要 .value 赋值，那是 ref 的用法）
  expanded.has(code) ? expanded.delete(code) : expanded.add(code)
}

function hostOf(url) {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

const statement = [
  {
    icon: 'M3 21h18M5 21V8l7-5 7 5v13M9 21v-6h6v6',
    title: '统计口径',
    lines: [
      '热度 = 词频 × (1 + 年份增长率)。',
      '同口径内归一化 0–100 排名。',
    ],
  },
  {
    icon: 'M12 3a13.5 13.5 0 0 1 0 18 13.5 13.5 0 0 1 0-18zM3 12h18',
    title: '数据来源',
    lines: [
      'CVF Open Access（CVPR / ICCV）· ECVA（ECCV）。',
      'Semantic Scholar 仅作摘要兜底。',
    ],
  },
  {
    icon: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 7v5l3 3',
    title: '范围与用途',
    lines: [
      '2022 年至今，仅元数据与摘要，不存 PDF。',
      '限速 ≤ 1 req/s，仅用于课程教学。',
    ],
  },
]

onMounted(async () => {
  try {
    conferences.value = await getConferences()
  } catch {
    degraded.value = true                  // 静默请求：降级内置文案，不弹 toast
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="about-view">
    <div class="page-head">
      <h1 class="page-title">关于三大顶会</h1>
      <p class="page-sub">
        CVPR · ICCV · ECCV —— 计算机视觉领域三大顶级会议的基本资料，
        点击卡片查看简介、举办周期、录用规模与官网链接。
      </p>
    </div>

    <el-alert
      v-if="degraded"
      title="后端暂不可达，当前展示内置默认介绍"
      type="warning"
      :closable="false"
      style="margin-bottom: 1rem"
    />

    <div v-if="loading" class="conf-grid">
      <div v-for="i in 3" :key="i" class="ct-card">
        <div class="skeleton" style="height:1.5rem;width:40%"></div>
        <div class="skeleton" style="height:.75rem;margin-top:1rem"></div>
        <div class="skeleton" style="height:.75rem;width:70%"></div>
      </div>
    </div>

    <div v-else class="conf-grid">
      <section
        v-for="c in conferences"
        :key="c.code"
        class="ct-card conf-card"
      >
        <button class="conf-head" type="button" @click="toggle(c.code)">
          <span class="conf-code ct-num">{{ c.code }}</span>
          <span class="conf-name">
            {{ c.name }}
            <small>{{ c.full_name }}</small>
          </span>
          <span class="spacer" />
          <svg
            class="chevron"
            :class="{ open: expanded.has(c.code) }"
            viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
          ><path d="m6 9 6 6 6-6"/></svg>
        </button>
        <el-collapse-transition>
          <div v-show="expanded.has(c.code)" class="conf-body">
            <p class="intro">{{ c.intro }}</p>
            <dl class="meta">
              <dt>举办周期</dt>
              <dd>{{ c.cycle }}</dd>
              <dt>录用规模</dt>
              <dd>{{ c.scale }}</dd>
            </dl>
            <a
              v-if="c.official_url"
              class="official" :href="c.official_url" target="_blank" rel="noopener"
            >
              官网：{{ hostOf(c.official_url) }} ↗
            </a>
          </div>
        </el-collapse-transition>
      </section>
    </div>

    <h2 class="section-title">数据说明</h2>
    <div class="statement-grid">
      <section v-for="s in statement" :key="s.title" class="ct-card statement-card">
        <h3 class="s-title">
          <svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path :d="s.icon" />
          </svg>
          {{ s.title }}
        </h3>
        <ul class="s-lines">
          <li v-for="line in s.lines" :key="line">{{ line }}</li>
        </ul>
      </section>
    </div>
  </div>
</template>

<style scoped>
.about-view {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.page-head {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}
.page-title {
  margin: 0;
  font-size: 1.375rem;
}
.page-sub {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--ct-text-sub);
}

.conf-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
}
@media (max-width: 56rem) {
  .conf-grid { grid-template-columns: 1fr; }
}
.conf-card {
  padding: 0;                                  /* 展开体自带留白，标题栏贴边 */
  overflow: hidden;
  min-height: 12rem;                           /* 折叠时也大于下方数据说明卡 */
  display: flex;
  flex-direction: column;
}
.conf-head {
  flex: 1;
  width: 100%;
  display: flex;
  align-items: center;
  gap: 0.875rem;
  padding: 1.875rem 1.5rem;
  background: transparent;
  border: none;
  color: var(--ct-text);
  text-align: left;
  cursor: pointer;
  transition: opacity 0.2s var(--ease, cubic-bezier(0.22, 1, 0.36, 1));
}
.conf-head:hover { opacity: 0.8; }
.conf-code {
  font-size: 2.125rem;
  font-weight: 800;
  /* 会议名渐变字（与首页搜索键同款 135° 墨蓝→雾紫，低饱和） */
  background: linear-gradient(135deg, #5A74AE, #9587C3);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.conf-name {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  font-weight: 700;
  font-size: 0.9375rem;
}
.conf-name small {
  font-weight: 400;
  font-size: 0.6875rem;
  color: var(--ct-text-weak);
  line-height: 1.5;
  /* 英文全名较长：自然换行完整显示，不截断 */
}
.spacer { flex: 1; }
.chevron {
  width: 1.125rem;
  height: 1.125rem;
  color: var(--ct-text-weak);
  transition: transform 0.25s var(--ease, cubic-bezier(0.22, 1, 0.36, 1));
}
.chevron.open { transform: rotate(180deg); }

.conf-body {
  padding: 0.25rem 1.5rem 1.5rem;
  border-top: 1px solid rgba(35, 38, 43, 0.06);
}
.intro {
  margin: 1.25rem 0 1rem;
  font-size: 0.8125rem;
  line-height: 2;
  color: var(--ct-text-sub);
}
.meta {
  margin: 0 0 1rem;
  display: grid;
  grid-template-columns: 4.5rem 1fr;
  row-gap: 0.5rem;
  font-size: 0.8125rem;
}
.meta dt { color: var(--ct-text-weak); }
.meta dd { color: var(--ct-text); }
.official {
  font-size: 0.8125rem;
  color: var(--ct-primary);
  text-decoration: none;
}
.official:hover { text-decoration: underline; }

.section-title {
  margin: 1rem 0 0;
  font-size: 1.125rem;
}
.statement-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
}
.statement-grid .ct-card {
  padding: 1.125rem 1.25rem;                   /* 数据说明卡短于会议卡 */
}
@media (max-width: 56rem) {
  .statement-grid { grid-template-columns: 1fr; }
}
.statement-card .s-title {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0 0 0.75rem;
  font-size: 0.9375rem;
}
.statement-card .s-title .ic { color: var(--ct-secondary); }
.s-lines {
  margin: 0;
  padding-left: 1.125rem;
  font-size: 0.8125rem;
  line-height: 1.7;
  color: var(--ct-text-sub);
}
</style>
