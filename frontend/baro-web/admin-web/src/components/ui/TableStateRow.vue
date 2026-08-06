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
      :style="{ paddingLeft: horizontalPadding, paddingRight: horizontalPadding }"
    >
      {{ message }}
    </td>
  </tr>
</template>

<style scoped>
.empty {
  padding-top: 40px;
  padding-bottom: 40px;
  text-align: center;
  color: var(--panel-muted-foreground);
}

.empty.error {
  color: var(--panel-danger);
}
</style>
