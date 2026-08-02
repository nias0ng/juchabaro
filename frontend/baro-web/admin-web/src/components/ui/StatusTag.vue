<script setup lang="ts">
export type TagTone = 'danger' | 'info' | 'success' | 'warning' | 'neutral' | 'primary';

withDefaults(defineProps<{ tone?: TagTone }>(), { tone: 'neutral' });
</script>

<template>
  <span class="tag" :class="`tone-${tone}`"><slot /></span>
</template>

<style scoped>
.tag {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-xxs);
  border-radius: var(--radius-sm);
  padding: 4px var(--spacing-sm);
  font-size: var(--font-size-sm);
  font-weight: 600;
  line-height: 1.4;
}

.tone-danger {
  background: var(--panel-danger-soft);
  color: var(--panel-danger);
}

.tone-info {
  background: var(--panel-info-soft);
  color: var(--panel-info);
}

.tone-success {
  background: var(--panel-success-soft);
  color: var(--panel-success);
}

.tone-warning {
  background: var(--panel-warning-soft);
  color: var(--panel-warning-foreground);
}

.tone-neutral {
  background: var(--panel-muted);
  color: var(--panel-muted-foreground);
}

.tone-primary {
  background: var(--panel-primary-soft);
  color: var(--panel-primary);
}
</style>
