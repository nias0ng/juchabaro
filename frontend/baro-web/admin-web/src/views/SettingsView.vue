<script setup lang="ts">
import { computed, ref } from 'vue'
import { Bell, Crosshair, ParkingSquare } from '@lucide/vue'

import AppShell from '@/components/layout/AppShell.vue'
import PageHeading from '@/components/ui/PageHeading.vue'
import InfoTooltip from '@/components/ui/InfoTooltip.vue'

// 현재 이 값들이 곧 기본값이며, "현재 적용 설정"의 초기화 버튼은 이 값들로 되돌린다.
const DEFAULT_STANDARDS = {
  parkingCompleteMinutes: 10,
  intrusionThresholdPercent: 40,
  recheckIntervalSeconds: 60,
}
const DEFAULT_TOGGLES = {
  disabledZoneWarningEnabled: true,
  evZoneWarningEnabled: true,
  pushNotificationEnabled: true,
  speakerAnnouncementEnabled: true,
  ledWarningEnabled: true,
  autoResendOnNoResponseEnabled: true,
}

const isEditingStandards = ref(false)
const parkingCompleteMinutes = ref(DEFAULT_STANDARDS.parkingCompleteMinutes)
const intrusionThresholdPercent = ref(DEFAULT_STANDARDS.intrusionThresholdPercent)
const recheckIntervalSeconds = ref(DEFAULT_STANDARDS.recheckIntervalSeconds)

const disabledZoneWarningEnabled = ref(DEFAULT_TOGGLES.disabledZoneWarningEnabled)
const evZoneWarningEnabled = ref(DEFAULT_TOGGLES.evZoneWarningEnabled)
// 전기차 충전 구역 허용 시간은 정책상 고정값이라 편집 UI가 없다.
const EV_FAST_CHARGE_HOURS = 1
const EV_SLOW_CHARGE_HOURS = 14

const pushNotificationEnabled = ref(DEFAULT_TOGGLES.pushNotificationEnabled)
const speakerAnnouncementEnabled = ref(DEFAULT_TOGGLES.speakerAnnouncementEnabled)
const ledWarningEnabled = ref(DEFAULT_TOGGLES.ledWarningEnabled)
const autoResendOnNoResponseEnabled = ref(DEFAULT_TOGGLES.autoResendOnNoResponseEnabled)

function resetToDefaults() {
  parkingCompleteMinutes.value = DEFAULT_STANDARDS.parkingCompleteMinutes
  intrusionThresholdPercent.value = DEFAULT_STANDARDS.intrusionThresholdPercent
  recheckIntervalSeconds.value = DEFAULT_STANDARDS.recheckIntervalSeconds
  disabledZoneWarningEnabled.value = DEFAULT_TOGGLES.disabledZoneWarningEnabled
  evZoneWarningEnabled.value = DEFAULT_TOGGLES.evZoneWarningEnabled
  pushNotificationEnabled.value = DEFAULT_TOGGLES.pushNotificationEnabled
  speakerAnnouncementEnabled.value = DEFAULT_TOGGLES.speakerAnnouncementEnabled
  ledWarningEnabled.value = DEFAULT_TOGGLES.ledWarningEnabled
  autoResendOnNoResponseEnabled.value = DEFAULT_TOGGLES.autoResendOnNoResponseEnabled
}

// 숫자만 입력받고, 단위(분/%/초)는 항상 고정 텍스트로 뒤에 붙인다.
function numericOnly(event: Event): number {
  const target = event.target as HTMLInputElement
  const digits = target.value.replace(/\D/g, '')
  return digits === '' ? 0 : Number(digits)
}

function onOffLabel(enabled: boolean) {
  return enabled ? '사용' : '미사용'
}

const APPLIED = computed(() => [
  {
    group: '관제 기준',
    items: [
      ['주차 완료 판단 시간', `${parkingCompleteMinutes.value}분`],
      ['침범 비율 임계값', `${intrusionThresholdPercent.value}%`],
      ['이동 확인 재검사 간격', `${recheckIntervalSeconds.value}초`],
    ],
  },
  {
    group: '전용 구역',
    items: [
      ['장애인 구역 경고 사용', onOffLabel(disabledZoneWarningEnabled.value)],
      ['전기차 구역 경고 사용', onOffLabel(evZoneWarningEnabled.value)],
      ['전기차 충전 구역 허용 시간', `${EV_SLOW_CHARGE_HOURS}시간`],
    ],
  },
  {
    group: '알림 및 현장 경고',
    items: [
      ['앱 푸시 알림', onOffLabel(pushNotificationEnabled.value)],
      ['현장 스피커 안내', onOffLabel(speakerAnnouncementEnabled.value)],
      ['LED 경고등', onOffLabel(ledWarningEnabled.value)],
      ['미응답 재알림 자동 발송', onOffLabel(autoResendOnNoResponseEnabled.value)],
    ],
  },
])
</script>

<template>
  <AppShell title="설정" breadcrumb="시스템 설정 관리">
    <PageHeading title="설정" desc="관제 기준, 알림 설정을 관리합니다." />

    <div class="layout">
      <div class="main-col">
        <section class="panel section-card">
          <div class="section-header">
            <div class="section-title">
              <span class="section-icon"><Crosshair :size="20" /></span>
              <h3>관제 기준 설정</h3>
            </div>
            <button
              type="button"
              class="edit-toggle"
              :class="{ active: isEditingStandards }"
              @click="isEditingStandards = !isEditingStandards"
            >
              {{ isEditingStandards ? '완료' : '수정' }}
            </button>
          </div>

          <div class="fields-grid">
            <div class="field">
              <span class="field-label">
                주차 완료 판단 시간
                <InfoTooltip text="AI가 주차 상태를 감지한 뒤, 정상 주차로 최종 확정하기까지 기다리는 시간입니다." />
              </span>
              <span v-if="isEditingStandards" class="field-input">
                <input
                  type="text"
                  inputmode="numeric"
                  :value="parkingCompleteMinutes"
                  @input="parkingCompleteMinutes = numericOnly($event)"
                >
                <span class="unit">분</span>
              </span>
              <span v-else class="field-static">{{ parkingCompleteMinutes }}분</span>
            </div>

            <div class="field">
              <span class="field-label">
                침범 비율 임계값
                <InfoTooltip text="차량이 주차 구역 경계를 벗어난 비율이 이 값을 넘으면 위반(침범)으로 판단합니다." />
              </span>
              <span v-if="isEditingStandards" class="field-input">
                <input
                  type="text"
                  inputmode="numeric"
                  :value="intrusionThresholdPercent"
                  @input="intrusionThresholdPercent = numericOnly($event)"
                >
                <span class="unit">%</span>
              </span>
              <span v-else class="field-static">{{ intrusionThresholdPercent }}%</span>
            </div>

            <div class="field">
              <span class="field-label">
                이동 확인 재검사 간격
                <InfoTooltip text="이동 요청을 보낸 뒤, 차량이 실제로 이동했는지 다시 확인하는 주기입니다." />
              </span>
              <span v-if="isEditingStandards" class="field-input">
                <input
                  type="text"
                  inputmode="numeric"
                  :value="recheckIntervalSeconds"
                  @input="recheckIntervalSeconds = numericOnly($event)"
                >
                <span class="unit">초</span>
              </span>
              <span v-else class="field-static">{{ recheckIntervalSeconds }}초</span>
            </div>
          </div>
        </section>

        <section class="panel section-card">
          <div class="section-header">
            <div class="section-title">
              <span class="section-icon"><ParkingSquare :size="20" /></span>
              <h3>전용 구역 설정</h3>
            </div>
          </div>

          <div class="zone-row">
            <div class="toggle-field">
              <span class="field-label">
                장애인 구역 경고 사용
                <InfoTooltip text="장애인 전용 구역에 일반 차량이 주차하면 경고를 표시할지 설정합니다." />
              </span>
              <button
                type="button"
                class="toggle"
                :class="{ on: disabledZoneWarningEnabled }"
                role="switch"
                :aria-checked="disabledZoneWarningEnabled"
                aria-label="장애인 구역 경고 사용"
                @click="disabledZoneWarningEnabled = !disabledZoneWarningEnabled"
              >
                <span class="toggle-knob" />
              </button>
            </div>
            <div class="toggle-field">
              <span class="field-label">
                전기차 구역 경고 사용
                <InfoTooltip text="전기차 전용 구역에 일반 차량이 주차하면 경고를 표시할지 설정합니다." />
              </span>
              <button
                type="button"
                class="toggle"
                :class="{ on: evZoneWarningEnabled }"
                role="switch"
                :aria-checked="evZoneWarningEnabled"
                aria-label="전기차 구역 경고 사용"
                @click="evZoneWarningEnabled = !evZoneWarningEnabled"
              >
                <span class="toggle-knob" />
              </button>
            </div>
            <div class="ev-time-row">
              <span class="field-label">
                전기차 충전 구역 허용 시간
                <InfoTooltip text="전기차 충전 구역에서 법적으로 허용되는 충전 최대 시간입니다. 이 값은 고정값입니다." />
              </span>
              <span class="ev-sub">충전 최대 시간</span>
              <span class="ev-value">{{ EV_SLOW_CHARGE_HOURS }}시간</span>
            </div>
          </div>
        </section>

        <section class="panel section-card">
          <div class="section-header">
            <div class="section-title">
              <span class="section-icon"><Bell :size="20" /></span>
              <h3>알림 및 현장 경고</h3>
            </div>
          </div>
          <div class="toggle-grid">
            <div class="toggle-field">
              <span class="field-label">
                앱 푸시 알림
                <InfoTooltip text="사건 발생·처리 결과를 관리자 앱으로 푸시 알림을 보낼지 설정합니다." />
              </span>
              <button
                type="button"
                class="toggle"
                :class="{ on: pushNotificationEnabled }"
                role="switch"
                :aria-checked="pushNotificationEnabled"
                aria-label="앱 푸시 알림"
                @click="pushNotificationEnabled = !pushNotificationEnabled"
              >
                <span class="toggle-knob" />
              </button>
            </div>
            <div class="toggle-field">
              <span class="field-label">
                현장 스피커 안내
                <InfoTooltip text="위반 감지 시 현장 스피커로 안내 방송을 재생할지 설정합니다." />
              </span>
              <button
                type="button"
                class="toggle"
                :class="{ on: speakerAnnouncementEnabled }"
                role="switch"
                :aria-checked="speakerAnnouncementEnabled"
                aria-label="현장 스피커 안내"
                @click="speakerAnnouncementEnabled = !speakerAnnouncementEnabled"
              >
                <span class="toggle-knob" />
              </button>
            </div>
            <div class="toggle-field">
              <span class="field-label">
                LED 경고등
                <InfoTooltip text="위반 감지 시 해당 구역의 LED 경고등을 점등할지 설정합니다." />
              </span>
              <button
                type="button"
                class="toggle"
                :class="{ on: ledWarningEnabled }"
                role="switch"
                :aria-checked="ledWarningEnabled"
                aria-label="LED 경고등"
                @click="ledWarningEnabled = !ledWarningEnabled"
              >
                <span class="toggle-knob" />
              </button>
            </div>
            <div class="toggle-field">
              <span class="field-label">
                미응답 재알림 자동 발송
                <InfoTooltip text="차주가 일정 시간 응답하지 않으면 이동 요청을 자동으로 재전송할지 설정합니다." />
              </span>
              <button
                type="button"
                class="toggle"
                :class="{ on: autoResendOnNoResponseEnabled }"
                role="switch"
                :aria-checked="autoResendOnNoResponseEnabled"
                aria-label="미응답 재알림 자동 발송"
                @click="autoResendOnNoResponseEnabled = !autoResendOnNoResponseEnabled"
              >
                <span class="toggle-knob" />
              </button>
            </div>
          </div>
        </section>
      </div>

      <aside class="panel applied-panel">
        <div class="section-title">
          <span class="section-icon"><Crosshair :size="20" /></span>
          <h3>현재 적용 설정</h3>
        </div>
        <div class="applied-groups">
          <div v-for="g in APPLIED" :key="g.group">
            <p class="group-title">{{ g.group }}</p>
            <ul class="group-list">
              <li v-for="[k, v] in g.items" :key="k">
                <span class="muted">• {{ k }}</span>
                <span class="value">{{ v }}</span>
              </li>
            </ul>
          </div>
        </div>
        <div class="applied-actions">
          <button type="button" class="ghost-primary-btn" @click="resetToDefaults">초기화</button>
        </div>
      </aside>
    </div>
  </AppShell>
</template>

<style scoped>
.layout {
  display: grid;
  gap: var(--spacing-lg);
  grid-template-columns: minmax(0, 1fr);
}

@media (min-width: 1280px) {
  .layout {
    grid-template-columns: minmax(0, 2.2fr) minmax(0, 1fr);
  }
}

.main-col {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-lg);
}

.section-card,
.applied-panel {
  padding: var(--spacing-lg);
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-base);
  /* React판 mb-5(20px). 이 값은 기존 spacing 토큰 단계(16/24)에 없어 그대로 px로 둔다. */
  margin-bottom: 20px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: var(--spacing-base);
  margin-bottom: 20px;
}

.section-header .section-title {
  margin-bottom: 0;
}

.section-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  background: var(--panel-primary-soft);
  color: var(--panel-primary);
}

.section-title h3 {
  font-size: var(--font-size-lg);
  font-weight: 700;
}

.edit-toggle {
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-md);
  background: none;
  padding: 6px var(--spacing-base);
  font-size: 12px;
  font-weight: 500;
  color: inherit;
  white-space: nowrap;
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.edit-toggle:hover {
  background: var(--panel-muted);
}

.edit-toggle.active {
  border-color: transparent;
  background: var(--panel-primary);
  color: var(--panel-on-primary);
  font-weight: 600;
}

.fields-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 20px;
}

@media (min-width: 768px) {
  .fields-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

.field {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-md);
}

.field-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--font-size-sm);
}

.field-static {
  min-width: 130px;
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-md);
  padding: var(--spacing-sm) var(--spacing-base);
  font-size: var(--font-size-sm);
  color: var(--panel-muted-foreground);
}

.field-input {
  display: flex;
  min-width: 130px;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  border: 1px solid color-mix(in oklch, var(--panel-primary) 40%, transparent);
  border-radius: var(--radius-md);
  padding: var(--spacing-sm) var(--spacing-base);
  font-size: var(--font-size-sm);
}

.field-input input {
  width: 40px;
  border: none;
  background: none;
  outline: none;
  text-align: right;
  color: inherit;
  font-size: var(--font-size-sm);
}

.field-input .unit {
  color: var(--panel-muted-foreground);
}

.zone-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-xl);
}

.toggle-field {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
}

.ev-time-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-base);
}

.ev-sub {
  font-size: var(--font-size-sm);
  color: var(--panel-muted-foreground);
}

.ev-value {
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-md);
  padding: var(--spacing-sm) var(--spacing-base);
  font-size: var(--font-size-sm);
}

.toggle {
  display: flex;
  align-items: center;
  width: 44px;
  height: 24px;
  border: none;
  border-radius: var(--radius-full);
  padding: 2px;
  background: var(--panel-muted);
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.toggle.on {
  background: var(--panel-primary);
}

.toggle-knob {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--panel-card);
  transition: transform 0.15s ease;
}

.toggle.on .toggle-knob {
  transform: translateX(20px);
}

.toggle-grid {
  display: flex;
  flex-wrap: wrap;
  /* React판 gap-y-5(20px) gap-x-10(40px) */
  gap: 20px 40px;
}

.applied-panel {
  height: fit-content;
}

.applied-groups {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.group-title {
  margin-bottom: var(--spacing-sm);
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--panel-primary);
}

.group-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: var(--font-size-sm);
}

.group-list li {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--spacing-base);
}

.muted {
  color: var(--panel-muted-foreground);
}

.value {
  font-weight: 600;
  white-space: nowrap;
}

.applied-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--spacing-sm);
  margin-top: var(--spacing-lg);
}

.ghost-primary-btn {
  border-radius: var(--radius-md);
  padding: var(--spacing-sm) var(--spacing-md);
  font-size: var(--font-size-sm);
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  border: 1px solid color-mix(in oklch, var(--panel-primary) 40%, transparent);
  background: none;
  color: var(--panel-primary);
  transition: background-color 0.15s ease;
}

.ghost-primary-btn:hover {
  background: var(--panel-primary-soft);
}
</style>
