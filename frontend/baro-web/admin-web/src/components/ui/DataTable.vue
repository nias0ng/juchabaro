<script setup lang="ts">
// ParkingEventListView/HistoryView/ParkingZoneManagementView가 각자 구현하던 표 뼈대
// (가로 스크롤, 기본 table/th/td, 행 구분선, strong/muted/nowrap 텍스트 스타일)를 공용으로
// 뺐다. thead/tbody 내용은 화면마다 완전히 달라서 슬롯으로 그대로 받고, 클릭으로 선택하는
// 화면(사건 목록/구역 관리)만 clickableRows로 hover·선택 강조를 켠다.
withDefaults(defineProps<{ clickableRows?: boolean }>(), {
  clickableRows: false,
})
</script>

<template>
  <div class="table-scroll">
    <table :class="{ 'clickable-rows': clickableRows }">
      <slot />
    </table>
  </div>
</template>

<style scoped>
.table-scroll {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-sm);
}

:slotted(thead tr) {
  border-bottom: 1px solid var(--panel-border);
  color: var(--panel-muted-foreground);
}

:slotted(th) {
  padding: var(--spacing-sm);
  text-align: left;
  font-weight: 500;
  white-space: nowrap;
}

:slotted(td) {
  padding: 14px var(--spacing-sm);
}

:slotted(.row) {
  border-bottom: 1px solid color-mix(in oklch, var(--panel-border) 70%, transparent);
}

:slotted(.row:last-child) {
  border-bottom: none;
}

.clickable-rows :slotted(.row) {
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.clickable-rows :slotted(.row:hover) {
  background: var(--panel-muted);
}

.clickable-rows :slotted(.row.selected) {
  background: var(--panel-primary-soft);
}

:slotted(.strong) {
  font-weight: 600;
}

:slotted(.muted) {
  color: var(--panel-muted-foreground);
}

:slotted(.nowrap) {
  white-space: nowrap;
}
</style>
