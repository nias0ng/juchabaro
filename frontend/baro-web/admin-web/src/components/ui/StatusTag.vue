<script setup lang="ts">
export type TagTone =
  | 'danger'
  | 'info'
  | 'success'
  | 'warning'
  | 'orange'
  | 'sky'
  | 'neutral'
  | 'primary'
  | 'plain'
  | 'red'
  | 'blue'
  | 'amber';

withDefaults(defineProps<{ tone?: TagTone; variant?: 'solid' | 'text' }>(), {
  tone: 'neutral',
  variant: 'solid',
});
</script>

<template>
  <span class="tag" :class="[`tone-${tone}`, variant === 'text' && 'variant-text']"><slot /></span>
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
  white-space: nowrap;
}

.tone-danger {
  background: var(--panel-danger-soft);
  color: var(--panel-danger);
}

.tone-info {
  background: var(--panel-info-soft);
  color: var(--panel-info);
}

.tone-sky {
  background: var(--panel-sky-soft);
  color: var(--panel-sky-foreground);
}

.tone-success {
  background: var(--panel-success-soft);
  color: var(--panel-success);
}

.tone-warning {
  background: var(--panel-warning-soft);
  color: var(--panel-warning-foreground);
}

.tone-orange {
  background: var(--panel-warning-soft);
  color: color-mix(in oklch, var(--panel-warning) 72%, var(--panel-foreground));
}

.tone-neutral {
  background: var(--panel-muted);
  color: var(--panel-muted-foreground);
}

.tone-primary {
  background: var(--panel-primary-soft);
  color: var(--panel-primary);
}

.tone-plain {
  background: transparent;
  color: var(--panel-foreground);
}

/* red/blue는 danger/info를 그대로 쓰기엔 너무 쨍해서, orange처럼 foreground를 섞어 눌러준다. */
.tone-red {
  background: var(--panel-danger-soft);
  color: color-mix(in oklch, var(--panel-danger) 75%, var(--panel-foreground));
}

.tone-blue {
  background: var(--panel-info-soft);
  color: color-mix(in oklch, var(--panel-info) 75%, var(--panel-foreground));
}

/* warning/orange보다 채도 있는 노란-주황색이 필요할 때(예: 구역 "사용 중" 상태) 쓴다. */
.tone-amber {
  background: var(--panel-warning-soft);
  color: var(--panel-warning);
}

/* 배경 없이 글자만 보여줄 때 쓴다. 색상(tone)은 그대로 유지해 구분은 되게 한다. */
.variant-text {
  background: transparent;
  padding: 0;
}
</style>
