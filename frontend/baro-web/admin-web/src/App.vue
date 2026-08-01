<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
</script>

<template>
  <header>
    <nav>
      <RouterLink to="/home">대시보드</RouterLink>
      <RouterLink to="/events">사건 목록</RouterLink>
      <RouterLink to="/parking-zones">주차 구역 관리</RouterLink>
      <RouterLink to="/history">이력 관리</RouterLink>
      <RouterLink to="/settings">설정</RouterLink>
      <RouterLink to="/login">로그인</RouterLink>
    </nav>
  </header>

  <RouterView />
</template>

<style scoped>
nav {
  display: flex;
  gap: 1rem;
  padding: 1rem;
  border-bottom: 1px solid var(--color-border);
}
</style>
