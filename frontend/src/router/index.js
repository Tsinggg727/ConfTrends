import { createRouter, createWebHistory } from 'vue-router'

import BasicLayout from '@/layouts/BasicLayout.vue'

/**
 * 路由表 —— 对应《原型设计初稿 v3》的 6 个一级页面。
 * 全部挂在 BasicLayout 之下，保证顶部导航在每一页都出现。
 *
 * meta 说明：
 *   title     页面标题（写入 document.title，并在导航中作为名称）
 *   showBack  是否在导航栏左侧显示「← 返回」
 *   backText  返回按钮文案
 *   navKey    该页对应的一级导航项（详情页归到「论文管理」下高亮）
 */
const routes = [
  {
    path: '/',
    component: BasicLayout,
    children: [
      {
        path: '',
        name: 'home',
        component: () => import('@/views/HomeView.vue'),
        meta: { title: '首页', navKey: 'home' },
      },
      {
        path: 'trend',
        name: 'trend',
        component: () => import('@/views/TrendView.vue'),
        meta: { title: '热度走势对比', navKey: 'trend' },
      },
      {
        path: 'papers',
        name: 'paperList',
        component: () => import('@/views/PaperListView.vue'),
        meta: { title: '论文列表管理', navKey: 'papers' },
      },
      {
        path: 'papers/:id(\\d+)',
        name: 'paperDetail',
        component: () => import('@/views/PaperDetailView.vue'),
        meta: {
          title: '论文详情',
          navKey: 'papers',
          showBack: true,
          backText: '返回列表',
        },
      },
      {
        path: 'crawl',
        name: 'crawl',
        component: () => import('@/views/CrawlView.vue'),
        meta: { title: '论文爬取 / 导入', navKey: 'crawl', showBack: true },
      },
      {
        path: 'about',
        name: 'about',
        component: () => import('@/views/AboutView.vue'),
        meta: { title: '关于三大顶会', navKey: 'about' },
      },
      {
        path: ':pathMatch(.*)*',
        name: 'notFound',
        component: () => import('@/views/NotFoundView.vue'),
        meta: { title: '页面不存在' },
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((to) => {
  const title = to.meta?.title
  document.title = title ? `${title} · 顶会热词 ConfTrends` : '顶会热词 ConfTrends'
})

export default router
