<script setup lang="ts">
defineProps<{ title: string; desc?: string }>();
</script>

<template>
  <div class="heading">
    <h1>{{ title }}</h1>
    <p v-if="desc">{{ desc }}</p>
  </div>
</template>

<style scoped>
.heading {
  margin-bottom: 28px;
}

h1 {
  font-size: 36px;
  font-weight: 800;
  letter-spacing: -0.02em;
  line-height: 1.15;
}

p {
  margin-top: var(--spacing-sm);
  font-size: var(--font-size-md);
  color: var(--panel-muted-foreground);
}
</style>
