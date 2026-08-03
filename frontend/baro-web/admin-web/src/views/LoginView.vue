<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { Gauge } from '@lucide/vue'

import { useAuthStore } from '@/stores/auth-store'
import { ApiError } from '@/services/api-error'

const loginId = ref('')
const password = ref('')
const error = ref<string | null>(null)
const isSubmitting = ref(false)

const authStore = useAuthStore()
const router = useRouter()
const route = useRoute()

async function handleSubmit() {
  if (!loginId.value.trim() || !password.value) {
    error.value = '아이디와 비밀번호를 입력해주세요.'
    return
  }

  error.value = null
  isSubmitting.value = true

  try {
    await authStore.login(loginId.value, password.value)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/events'
    router.replace(redirect)
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '로그인에 실패했습니다. 다시 시도해주세요.'
    isSubmitting.value = false
  }
}
</script>

<template>
  <section class="login">
    <div class="panel card">
      <RouterLink to="/" class="brand-link">
        <Gauge :size="16" /> 주차바로
      </RouterLink>

      <h1>관리자 로그인</h1>
      <p class="subtitle">아이디와 비밀번호를 입력해주세요.</p>

      <form class="form" novalidate @submit.prevent="handleSubmit">
        <div class="field">
          <label for="loginId">아이디</label>
          <input
            id="loginId"
            v-model="loginId"
            type="text"
            autocomplete="username"
            :disabled="isSubmitting"
            aria-describedby="login-error"
          >
        </div>

        <div class="field">
          <label for="password">비밀번호</label>
          <input
            id="password"
            v-model="password"
            type="password"
            autocomplete="current-password"
            :disabled="isSubmitting"
            aria-describedby="login-error"
          >
        </div>

        <p v-if="error" id="login-error" role="alert" class="error">{{ error }}</p>

        <button type="submit" class="submit" :disabled="isSubmitting">
          {{ isSubmitting ? '로그인 중...' : '로그인' }}
        </button>
      </form>
    </div>
  </section>
</template>

<style scoped>
.login {
  display: flex;
  min-height: 100vh;
  align-items: center;
  justify-content: center;
  background: var(--panel-background);
  padding: 0 var(--spacing-md);
}

.card {
  width: 100%;
  max-width: 384px;
  padding: var(--spacing-xl);
}

.brand-link {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-lg);
  font-size: var(--font-size-sm);
  color: var(--panel-muted-foreground);
  text-decoration: none;
  transition: color 0.15s ease;
}

.brand-link:hover {
  color: var(--panel-primary);
}

h1 {
  font-size: var(--font-size-lg);
  font-weight: 700;
}

.subtitle {
  margin-top: 4px;
  font-size: var(--font-size-sm);
  color: var(--panel-muted-foreground);
}

.form {
  margin-top: var(--spacing-lg);
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
}

.field label {
  display: block;
  margin-bottom: 6px;
  font-size: var(--font-size-sm);
  font-weight: 500;
}

.field input {
  width: 100%;
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-md);
  background: var(--panel-background);
  padding: var(--spacing-sm) var(--spacing-base);
  font-size: var(--font-size-sm);
  color: inherit;
  outline: none;
}

.field input:focus {
  border-color: var(--panel-primary);
}

.field input:disabled {
  opacity: 0.6;
}

.error {
  font-size: var(--font-size-sm);
  color: var(--panel-danger);
}

.submit {
  width: 100%;
  border: none;
  border-radius: var(--radius-md);
  background: var(--panel-primary);
  padding: 10px var(--spacing-md);
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--panel-on-primary);
  box-shadow: var(--panel-shadow-pop);
  cursor: pointer;
  transition: opacity 0.15s ease;
}

.submit:hover:not(:disabled) {
  opacity: 0.9;
}

.submit:disabled {
  opacity: 0.6;
  cursor: default;
}
</style>
