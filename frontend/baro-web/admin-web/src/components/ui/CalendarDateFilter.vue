<script setup lang="ts">
import { CalendarDays, ChevronDown, ChevronLeft, ChevronRight, X } from '@lucide/vue'
import { computed, ref, watch } from 'vue'

const props = defineProps<{
  modelValue: string | null
  open: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string | null]
  toggle: []
  close: []
}>()

const WEEKDAY_LABELS = ['일', '월', '화', '수', '목', '금', '토']

function toDateString(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function parseDateString(value: string): Date {
  const [year, month, day] = value.split('-').map(Number)
  return new Date(year!, month! - 1, day!)
}

function startOfMonth(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1)
}

const today = new Date()
today.setHours(0, 0, 0, 0)
const todayString = toDateString(today)
const visibleMonth = ref(startOfMonth(props.modelValue ? parseDateString(props.modelValue) : today))

watch(
  () => props.open,
  (open) => {
    if (open) visibleMonth.value = startOfMonth(props.modelValue ? parseDateString(props.modelValue) : today)
  },
)

const triggerLabel = computed(() => props.modelValue?.replaceAll('-', '.') ?? '최근 14일')
const monthLabel = computed(
  () => `${visibleMonth.value.getFullYear()}년 ${visibleMonth.value.getMonth() + 1}월`,
)
const isCurrentMonth = computed(
  () =>
    visibleMonth.value.getFullYear() === today.getFullYear()
    && visibleMonth.value.getMonth() === today.getMonth(),
)

const calendarDays = computed(() => {
  const year = visibleMonth.value.getFullYear()
  const month = visibleMonth.value.getMonth()
  const firstDay = new Date(year, month, 1)
  const gridStart = new Date(year, month, 1 - firstDay.getDay())

  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(gridStart)
    date.setDate(gridStart.getDate() + index)
    const dateString = toDateString(date)

    return {
      dateString,
      day: date.getDate(),
      currentMonth: date.getMonth() === month,
      today: dateString === todayString,
      selected: dateString === props.modelValue,
      future: date > today,
    }
  })
})

function moveMonth(offset: number) {
  visibleMonth.value = new Date(
    visibleMonth.value.getFullYear(),
    visibleMonth.value.getMonth() + offset,
    1,
  )
}

function selectDate(value: string) {
  emit('update:modelValue', value)
  emit('close')
}

function selectRecentRange() {
  emit('update:modelValue', null)
  emit('close')
}
</script>

<template>
  <div class="calendar-filter">
    <button
      type="button"
      class="date-trigger"
      :class="{ active: modelValue !== null, expanded: open }"
      :aria-expanded="open"
      aria-haspopup="dialog"
      @click="emit('toggle')"
    >
      <span class="calendar-icon"><CalendarDays :size="16" :stroke-width="2" /></span>
      <span>{{ triggerLabel }}</span>
      <ChevronDown v-if="modelValue === null" class="trigger-chevron" :size="14" />
    </button>
    <button
      v-if="modelValue !== null"
      type="button"
      class="clear-date-button"
      aria-label="날짜 선택 초기화"
      title="최근 14일 전체로 돌아가기"
      @click="selectRecentRange"
    >
      <X :size="14" />
    </button>

    <div v-if="open" class="calendar-popover" role="dialog" aria-label="사건 날짜 선택">
      <div class="calendar-header">
        <button type="button" class="month-nav" aria-label="이전 달" @click="moveMonth(-1)">
          <ChevronLeft :size="17" />
        </button>
        <strong>{{ monthLabel }}</strong>
        <button
          type="button"
          class="month-nav"
          :disabled="isCurrentMonth"
          aria-label="다음 달"
          @click="moveMonth(1)"
        >
          <ChevronRight :size="17" />
        </button>
      </div>

      <div class="weekday-grid" aria-hidden="true">
        <span v-for="weekday in WEEKDAY_LABELS" :key="weekday">{{ weekday }}</span>
      </div>

      <div class="day-grid">
        <button
          v-for="date in calendarDays"
          :key="date.dateString"
          type="button"
          class="day-button"
          :class="{
            adjacent: !date.currentMonth,
            today: date.today,
            selected: date.selected,
          }"
          :disabled="date.future"
          :aria-label="date.dateString"
          :aria-pressed="date.selected"
          @click="selectDate(date.dateString)"
        >
          {{ date.day }}
        </button>
      </div>

      <div class="calendar-footer">
        <button type="button" class="range-button" @click="selectRecentRange">날짜 초기화</button>
        <button type="button" class="today-button" @click="selectDate(todayString)">오늘</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.calendar-filter {
  position: relative;
}

.date-trigger {
  display: inline-flex;
  align-items: center;
  height: 34px;
  gap: 7px;
  flex-shrink: 0;
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-md);
  background: var(--panel-card);
  padding: 0 10px 0 8px;
  color: var(--panel-muted-foreground);
  font-family: inherit;
  font-size: var(--font-size-sm);
  white-space: nowrap;
  cursor: pointer;
  transition: border-color 0.15s ease, background-color 0.15s ease, box-shadow 0.15s ease;
}

.date-trigger:hover,
.date-trigger.expanded {
  border-color: color-mix(in oklch, var(--panel-primary) 35%, var(--panel-border));
  background: var(--panel-primary-soft);
}

.date-trigger.expanded {
  box-shadow: 0 0 0 3px color-mix(in oklch, var(--panel-primary) 12%, transparent);
}

.date-trigger.active {
  border-color: color-mix(in oklch, var(--panel-primary) 40%, transparent);
  padding-right: 32px;
  color: var(--panel-primary);
  font-weight: 600;
}

.calendar-icon {
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  border-radius: 7px;
  background: var(--panel-primary-soft);
  color: var(--panel-primary);
}

.trigger-chevron {
  transition: transform 0.18s ease;
}

.date-trigger.expanded .trigger-chevron {
  transform: rotate(180deg);
}

.clear-date-button {
  position: absolute;
  top: 5px;
  right: 5px;
  z-index: 1;
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--panel-primary);
  cursor: pointer;
}

.clear-date-button:hover {
  background: color-mix(in oklch, var(--panel-primary) 14%, transparent);
}

.date-trigger:focus-visible,
.clear-date-button:focus-visible,
.month-nav:focus-visible,
.day-button:focus-visible,
.range-button:focus-visible,
.today-button:focus-visible {
  outline: 2px solid color-mix(in oklch, var(--panel-primary) 65%, transparent);
  outline-offset: 2px;
}

.calendar-popover {
  position: absolute;
  top: calc(100% + var(--spacing-sm));
  left: 0;
  z-index: 20;
  width: 296px;
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-lg);
  background: var(--panel-card);
  padding: var(--spacing-base);
  box-shadow: var(--panel-shadow-pop);
}

.calendar-header {
  display: grid;
  grid-template-columns: 32px 1fr 32px;
  align-items: center;
  margin-bottom: 10px;
  text-align: center;
}

.calendar-header strong {
  font-size: var(--font-size-md);
  color: var(--panel-foreground);
}

.month-nav {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--panel-muted-foreground);
  cursor: pointer;
}

.month-nav:hover:not(:disabled) {
  background: var(--panel-muted);
  color: var(--panel-foreground);
}

.month-nav:disabled {
  opacity: 0.28;
  cursor: default;
}

.weekday-grid,
.day-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
}

.weekday-grid {
  margin-bottom: 4px;
}

.weekday-grid span {
  display: grid;
  height: 26px;
  place-items: center;
  color: var(--panel-muted-foreground);
  font-size: var(--font-size-xs);
  font-weight: 600;
}

.weekday-grid span:first-child {
  color: var(--panel-danger);
}

.day-button {
  display: grid;
  width: 34px;
  height: 34px;
  place-self: center;
  place-items: center;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: var(--panel-foreground);
  font-family: inherit;
  font-size: var(--font-size-sm);
  cursor: pointer;
}

.day-button:hover:not(:disabled):not(.selected) {
  background: var(--panel-muted);
}

.day-button.adjacent {
  color: color-mix(in oklch, var(--panel-muted-foreground) 42%, transparent);
}

.day-button.today:not(.selected) {
  box-shadow: inset 0 0 0 1px color-mix(in oklch, var(--panel-primary) 45%, transparent);
  color: var(--panel-primary);
  font-weight: 700;
}

.day-button.selected {
  background: var(--panel-primary);
  color: var(--panel-on-primary);
  font-weight: 700;
  box-shadow: 0 5px 12px color-mix(in oklch, var(--panel-primary) 24%, transparent);
}

.day-button:disabled {
  opacity: 0.22;
  cursor: default;
}

.calendar-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-sm);
  margin-top: 10px;
  border-top: 1px solid var(--panel-border);
  padding-top: 10px;
}

.range-button,
.today-button {
  border: none;
  border-radius: var(--radius-sm);
  padding: 7px 10px;
  font-family: inherit;
  font-size: var(--font-size-sm);
  font-weight: 600;
  cursor: pointer;
}

.range-button {
  background: transparent;
  color: var(--panel-muted-foreground);
}

.range-button:hover {
  background: var(--panel-muted);
  color: var(--panel-foreground);
}

.today-button {
  background: var(--panel-primary-soft);
  color: var(--panel-primary);
}

.today-button:hover {
  background: color-mix(in oklch, var(--panel-primary) 18%, transparent);
}
</style>
