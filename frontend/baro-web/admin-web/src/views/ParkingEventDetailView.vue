<script setup lang="ts">
import { useRoute } from 'vue-router'

const route = useRoute()
const eventId = route.params.eventId
</script>

<template>
  <section>
    <h1>사건 상세 ({{ eventId }})</h1>
  </section>
</template>
