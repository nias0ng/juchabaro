import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '@/stores/auth-store'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'splash',
      component: () => import('../views/SplashView.vue'),
      meta: { public: true },
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/events',
      name: 'event-list',
      component: () => import('../views/ParkingEventListView.vue'),
    },
    {
      path: '/events/:eventId',
      name: 'event-detail',
      component: () => import('../views/ParkingEventDetailView.vue'),
    },
    {
      path: '/parking-zones',
      name: 'parking-zones',
      component: () => import('../views/ParkingZoneManagementView.vue'),
    },
    {
      path: '/history',
      name: 'history',
      component: () => import('../views/HistoryView.vue'),
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('../views/SettingsView.vue'),
    },
  ],
})

// 인증 여부 판단은 이 가드 한 곳에서만 한다 (admin-web/AGENTS.md "인증 기능" 참고).
router.beforeEach(async (to) => {
  const authStore = useAuthStore()
  await authStore.restoreSession()

  const isPublic = to.meta.public === true

  if (!isPublic && authStore.status !== 'authenticated') {
    return { name: 'login', query: { redirect: to.fullPath } }
  }

  // 스플래시('/')·로그인 화면은 게스트 전용이라, 이미 로그인된 사용자는 사건 목록으로 보낸다.
  if (isPublic && authStore.status === 'authenticated') {
    return { name: 'event-list' }
  }
})

export default router
