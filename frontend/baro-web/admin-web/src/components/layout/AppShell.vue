<script setup lang="ts">
import { RouterLink, useRoute, useRouter } from 'vue-router';
import { Car, ChevronDown, Gauge, History, LogOut, Settings, SquareDot, User } from '@lucide/vue';

import { useDropdownFilter } from '@/composables/use-dropdown-filter';
import { useAuthStore } from '@/stores/auth-store';

defineProps<{ title: string; breadcrumb: string }>();

const NAV = [
  { to: '/events', label: '사건 목록', icon: SquareDot },
  { to: '/parking-zones', label: '주차 구역 관리', icon: Car },
  { to: '/history', label: '이력 관리', icon: History },
  { to: '/settings', label: '설정', icon: Settings },
] as const;

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const { filterBarRef: userMenuRef, openDropdown: openUserMenu, toggleDropdown: toggleUserMenu } =
  useDropdownFilter<'user'>();

function isActive(to: string) {
  return route.path === to || route.path.startsWith(`${to}/`);
}

function handleLogout() {
  authStore.logout();
  router.push('/');
}
</script>

<template>
  <div class="shell">
    <aside class="sidebar sidebar-surface">
      <div>
        <div class="brand">
          <div class="brand-icon">
            <Gauge :size="24" />
          </div>
          <div>
            <p class="brand-title">주차바로</p>
            <p class="brand-sub">스마트 주차 관리솔루션</p>
          </div>
        </div>
        <nav class="nav">
          <RouterLink
            v-for="item in NAV"
            :key="item.to"
            :to="item.to"
            class="nav-item"
            :class="{ active: isActive(item.to) }"
          >
            <component :is="item.icon" :size="18" />
            {{ item.label }}
          </RouterLink>
        </nav>
      </div>
      <div class="logout-wrap">
        <button type="button" class="logout-btn" @click="handleLogout">
          <LogOut :size="18" />
          로그아웃
        </button>
      </div>
    </aside>

    <div class="content">
      <header class="topbar">
        <div class="topbar-left">
          <h2>{{ title }}</h2>
          <span class="topbar-divider" />
          <p class="breadcrumb">{{ breadcrumb }}</p>
        </div>
        <div ref="userMenuRef" class="topbar-right user-menu-wrap">
          <button type="button" class="user-btn" @click="toggleUserMenu('user')">
            <span class="avatar">
              <User :size="16" />
            </span>
            <span class="user-name">관리자</span>
            <ChevronDown :size="16" />
          </button>
          <div v-if="openUserMenu === 'user'" class="user-menu">
            <button type="button" class="user-menu-item" @click="handleLogout">
              <LogOut :size="16" />
              로그아웃
            </button>
          </div>
        </div>
      </header>
      <main class="main">
        <slot />
      </main>
    </div>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  min-height: 100vh;
  background: var(--panel-background);
}

.sidebar {
  /* AGENTS.md: 태블릿 폭(Breakpoints.tablet = 768px)부터 사이드바를 유지한다. */
  display: none;
  position: sticky;
  top: 0;
  flex-direction: column;
  justify-content: space-between;
  flex-shrink: 0;
  width: 256px;
  height: 100vh;
  padding: var(--spacing-lg) var(--spacing-md);
}

@media (min-width: 768px) {
  .sidebar {
    display: flex;
  }
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--spacing-base);
  margin-bottom: var(--spacing-xl);
  padding: 0 var(--spacing-xs);
}

.brand-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: var(--radius-lg);
  background: var(--panel-card);
  box-shadow: var(--panel-shadow-card);
  color: var(--panel-primary);
}

.brand-title {
  font-size: var(--font-size-lg);
  font-weight: 700;
  color: var(--panel-sidebar-foreground);
}

.brand-sub {
  font-size: var(--font-size-xs);
  color: var(--panel-muted-foreground);
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: var(--spacing-base);
  border-radius: var(--radius-md);
  padding: var(--spacing-base) var(--spacing-md);
  font-size: var(--font-size-md);
  font-weight: 500;
  color: color-mix(in oklch, var(--panel-sidebar-foreground) 80%, transparent);
  text-decoration: none;
  transition: background-color 0.15s ease;
}

.nav-item:hover {
  background: var(--panel-sidebar-hover);
}

.nav-item.active {
  background: var(--panel-sidebar-active);
  color: var(--panel-sidebar-active-foreground);
  font-weight: 600;
  box-shadow: var(--panel-shadow-card);
}

.logout-wrap {
  border-top: 1px solid var(--panel-sidebar-border);
  padding-top: var(--spacing-md);
}

.logout-btn {
  display: flex;
  align-items: center;
  gap: var(--spacing-base);
  width: 100%;
  border: none;
  background: none;
  border-radius: var(--radius-md);
  padding: var(--spacing-base) var(--spacing-md);
  font-size: var(--font-size-md);
  font-weight: 500;
  color: color-mix(in oklch, var(--panel-sidebar-foreground) 80%, transparent);
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.logout-btn:hover {
  background: var(--panel-sidebar-hover);
}

.content {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--panel-border);
  background: color-mix(in oklch, var(--panel-card) 90%, transparent);
  backdrop-filter: blur(8px);
  padding: var(--spacing-md) var(--spacing-lg);
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
}

.topbar-left h2 {
  font-size: var(--font-size-base);
  font-weight: 700;
}

.topbar-divider {
  display: none;
  width: 1px;
  height: 16px;
  background: var(--panel-border);
}

.breadcrumb {
  display: none;
  font-size: var(--font-size-md);
  color: var(--panel-muted-foreground);
}

@media (min-width: 640px) {
  .topbar-divider,
  .breadcrumb {
    display: block;
  }
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
}

.user-btn {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-full);
  background: none;
  padding: 6px var(--spacing-base) 6px 6px;
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.user-btn:hover {
  background: var(--panel-muted);
}

.avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: var(--radius-full);
  background: var(--panel-muted);
  color: var(--panel-muted-foreground);
}

.user-name {
  font-size: var(--font-size-md);
  font-weight: 500;
}

.user-menu-wrap {
  position: relative;
}

.user-menu {
  position: absolute;
  top: calc(100% + var(--spacing-sm));
  right: 0;
  z-index: 10;
  width: 144px;
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-md);
  background: var(--panel-card);
  padding: 6px;
  box-shadow: var(--panel-shadow-card);
}

.user-menu-item {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  width: 100%;
  border: none;
  background: none;
  border-radius: 6px;
  padding: var(--spacing-sm) var(--spacing-base);
  font-size: var(--font-size-sm);
  font-weight: 500;
  color: var(--panel-danger);
  cursor: pointer;
}

.user-menu-item:hover {
  background: var(--panel-muted);
}

.main {
  flex: 1;
  padding: var(--spacing-xl) var(--spacing-lg);
}
</style>
