<script setup lang="ts">
withDefaults(
  defineProps<{
    colspan: number
    variant: 'loading' | 'error' | 'empty'
    message: string
    horizontalPadding?: string
  }>(),
  { horizontalPadding: 'var(--spacing-sm)' },
)
</script>

<template>
  <tr>
    <td
      :colspan="colspan"
      class="empty"
      :class="{ error: variant === 'error' }"
      :style="{ '--table-state-row-padding-x': horizontalPadding }"
    >
      {{ message }}
    </td>
  </tr>
</template>

<style scoped>
.empty {
  padding-block: 40px;
  padding-inline: var(--table-state-row-padding-x, var(--spacing-sm));
  text-align: center;
  color: var(--panel-muted-foreground);
}

.empty.error {
  color: var(--panel-danger);
}
</style>
