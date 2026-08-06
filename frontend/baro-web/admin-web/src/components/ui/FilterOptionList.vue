<script setup lang="ts" generic="T extends string">
// ParkingEventListView/ParkingZoneManagementView가 동일한 구조("전체" + 옵션 목록
// 버튼)로 구현하던 드롭다운 본문을 공용으로 뺐다. 열림/닫힘 상태(한 번에 하나만 열리게)는
// 계속 각 화면의 useDropdownFilter가 관리하고, 이 컴포넌트는 그 안의 옵션 목록만 그린다.
withDefaults(
  defineProps<{
    options: T[]
    selected: T | null
    labelFor: (value: T) => string
    width?: string
  }>(),
  { width: '144px' },
)

const emit = defineEmits<{ select: [value: T | null] }>()
</script>

<template>
  <div class="dropdown-menu" :style="{ '--filter-option-list-width': width }">
    <button
      type="button"
      class="dropdown-item"
      :class="{ selected: selected === null }"
      @click="emit('select', null)"
    >
      전체
    </button>
    <button
      v-for="opt in options"
      :key="opt"
      type="button"
      class="dropdown-item"
      :class="{ selected: selected === opt }"
      @click="emit('select', opt)"
    >
      {{ labelFor(opt) }}
    </button>
  </div>
</template>

<style scoped>
.dropdown-menu {
  position: absolute;
  left: 0;
  top: 100%;
  z-index: 10;
  margin-top: var(--spacing-sm);
  width: var(--filter-option-list-width, 144px);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-md);
  background: var(--panel-card);
  padding: 6px;
  box-shadow: var(--panel-shadow-card);
}

.dropdown-item {
  display: block;
  width: 100%;
  border: none;
  background: none;
  border-radius: 6px;
  padding: 6px var(--spacing-base);
  text-align: left;
  font-size: var(--font-size-sm);
  cursor: pointer;
}

.dropdown-item:hover {
  background: var(--panel-muted);
}

.dropdown-item.selected {
  color: var(--panel-primary);
  font-weight: 600;
}
</style>
