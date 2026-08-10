<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { Gauge } from '@lucide/vue'
</script>

<template>
  <section class="splash">
    <div class="panel card">
      <div class="icon-wrap">
        <Gauge :size="32" />
      </div>
      <div>
        <h1>주차바로</h1>
        <p>스마트 주차 관리솔루션</p>
      </div>
      <RouterLink to="/login" class="cta">관리자 로그인</RouterLink>
    </div>
  </section>
</template>

<style scoped>
.splash {
  display: flex;
  min-height: 100vh;
  align-items: center;
  justify-content: center;
  background: var(--panel-background);
  padding: 0 var(--spacing-md);
}

.card {
  display: flex;
  width: 100%;
  max-width: 384px;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-lg);
  padding: var(--spacing-xl);
  text-align: center;
}

.icon-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 64px;
  height: 64px;
  border-radius: var(--radius-lg);
  background: var(--panel-primary-soft);
  color: var(--panel-primary);
}

h1 {
  font-size: var(--font-size-xl);
  font-weight: 700;
}

.card p {
  margin-top: 4px;
  font-size: var(--font-size-sm);
  color: var(--panel-muted-foreground);
}

.cta {
  display: inline-flex;
  width: 100%;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  background: var(--panel-primary);
  padding: var(--spacing-base) var(--spacing-md);
  font-size: var(--font-size-md);
  font-weight: 600;
  color: var(--panel-on-primary);
  text-decoration: none;
  box-shadow: var(--panel-shadow-pop);
  transition: opacity 0.15s ease;
}

.cta:hover {
  opacity: 0.9;
}
</style>
