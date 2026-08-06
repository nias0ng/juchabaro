import { computed, ref, watch } from 'vue';

import { useAutoRefresh } from '@/composables/use-auto-refresh';
import { getParkingZoneSummary, getZones, updateZone } from '@/features/parking-zones/api/parking-zone-api';
import type { OccupancyStatus, ParkingSpotSummary, ZoneCatalogItem, ZoneType } from '@/features/parking-zones/api/types';
import {
  compareZoneNumbers,
  computeFloorCongestion,
  findSpotSummary,
  hoursToMinutes,
  minutesToHours,
  zoneFloorOf,
} from '@/features/parking-zones/data';
import type { FloorKey } from '@/features/parking-zones/types';
import { useAuthStore } from '@/stores/auth-store';

// B1의 실제 물리 배치를 그대로 복제해 B2/B3에도 등록해 뒀다(features/parking-zones/data.ts의
// floorZoneLayout 참고).
const FLOOR_KEYS: FloorKey[] = ['B1', 'B2', 'B3'];

// 구역 번호·유형·허용 시간은 관리자가 바꿀 수 있다(PATCH /api/zones/{zoneId}). 점유 상태는
// 실제 감지 데이터라 여기서 바꿀 수 없다.
type EditDraft = {
  zoneNumber: string;
  zoneType: ZoneType;
  // <input type="number">는 값이 있으면 Vue가 자동으로 number로, 비우면 ''(문자열)로 바꾼다.
  // 비워두면 이 필드를 요청에서 빼서 값을 바꾸지 않는다(백엔드가 "무제한으로 되돌리기"를
  // 어떻게 표현하는지 명세에 없음). 화면은 시간 단위로 보여주고 저장 시 분으로 환산한다.
  allowedHours: number | '';
};

export function useZoneManagement() {
  const authStore = useAuthStore();

  const selectedFloor = ref<FloorKey>('B1');

  const zones = ref<ZoneCatalogItem[]>([]);
  const zonesLoading = ref(false);
  const zonesError = ref<string | null>(null);

  const spots = ref<ParkingSpotSummary[]>([]);
  const summaryLoading = ref(false);
  const summaryError = ref<string | null>(null);
  let zonesRequestId = 0;
  let summaryRequestId = 0;

  async function loadZones(background = false) {
    if (background && zonesLoading.value) return;
    const requestId = ++zonesRequestId;
    const showLoading = !background || zones.value.length === 0;
    if (showLoading) zonesLoading.value = true;
    if (!background) zonesError.value = null;
    try {
      const accessToken = authStore.accessToken;
      if (!accessToken) throw new Error('로그인이 필요합니다.');
      const result = await getZones(accessToken);
      if (requestId === zonesRequestId) {
        zones.value = result.zones;
        zonesError.value = null;
      }
    } catch (error) {
      if (requestId === zonesRequestId && showLoading) {
        zonesError.value = error instanceof Error ? error.message : '구역 목록을 불러오지 못했습니다.';
      }
    } finally {
      if (requestId === zonesRequestId && showLoading) zonesLoading.value = false;
    }
  }

  async function loadSummary(background = false) {
    if (background && summaryLoading.value) return;
    const requestId = ++summaryRequestId;
    const showLoading = !background || spots.value.length === 0;
    if (showLoading) summaryLoading.value = true;
    if (!background) summaryError.value = null;
    try {
      const accessToken = authStore.accessToken;
      if (!accessToken) throw new Error('로그인이 필요합니다.');
      const result = await getParkingZoneSummary(accessToken);
      if (requestId === summaryRequestId) {
        spots.value = result.spots;
        summaryError.value = null;
      }
    } catch (error) {
      if (requestId === summaryRequestId && showLoading) {
        summaryError.value = error instanceof Error ? error.message : '주차 구역 현황을 불러오지 못했습니다.';
      }
    } finally {
      if (requestId === summaryRequestId && showLoading) summaryLoading.value = false;
    }
  }

  void loadZones();
  void loadSummary();
  useAutoRefresh(
    () => Promise.all([loadZones(true), loadSummary(true)]).then(() => undefined),
    30_000,
  );

  const typeFilter = ref<ZoneType | null>(null);
  const statusFilter = ref<OccupancyStatus | null>(null);
  const codeQuery = ref('');
  const selectedZoneId = ref<number | null>(null);
  const editDraft = ref<EditDraft | null>(null);
  const saveError = ref<string | null>(null);
  const saving = ref(false);

  function occupancyOf(zoneId: number): OccupancyStatus | null {
    return findSpotSummary(spots.value, zoneId)?.occupancyStatus ?? null;
  }

  // GET /api/parking-zones/summary가 층 구분 없이 전체를 한 번에 반환하기 때문에, 혼잡도는
  // 응답 최상위 값 대신 선택한 층의 구역만 걸러서 화면에서 직접 계산한다.
  const congestion = computed(() => computeFloorCongestion(selectedFloor.value, spots.value));

  const floorZones = computed(() =>
    zones.value
      .filter((z) => zoneFloorOf(z.zoneNumber) === selectedFloor.value)
      .slice()
      .sort((a, b) => compareZoneNumbers(a.zoneNumber, b.zoneNumber)),
  );

  const zoneStats = computed(() => ({
    total: floorZones.value.length,
    general: floorZones.value.filter((z) => z.zoneType === 'GENERAL').length,
    disabled: floorZones.value.filter((z) => z.zoneType === 'DISABLED').length,
    ev: floorZones.value.filter((z) => z.zoneType === 'EV_CHARGING').length,
  }));

  const filteredRows = computed(() => {
    const query = codeQuery.value.trim().toUpperCase();
    return floorZones.value.filter((z) => {
      if (typeFilter.value && z.zoneType !== typeFilter.value) return false;
      if (statusFilter.value && occupancyOf(z.zoneId) !== statusFilter.value) return false;
      if (query && !z.zoneNumber.toUpperCase().includes(query)) return false;
      return true;
    });
  });

  const selectedZone = computed(
    () => zones.value.find((z) => z.zoneId === selectedZoneId.value) ?? filteredRows.value[0] ?? null,
  );

  // 층 탭을 바꾸면 이전 층에서 고르던 구역 선택을 초기화해, 다른 층 이름의 구역이 그대로
  // "선택 구역 정보"에 남아있지 않게 한다.
  watch(selectedFloor, () => {
    selectedZoneId.value = null;
    editDraft.value = null;
    saveError.value = null;
  });

  function selectZoneId(zoneId: number) {
    selectedZoneId.value = zoneId;
    editDraft.value = null;
    saveError.value = null;
  }

  function selectSpot(spot: ParkingSpotSummary) {
    selectZoneId(spot.zoneId);
  }

  function startEdit() {
    if (!selectedZone.value) return;
    editDraft.value = {
      zoneNumber: selectedZone.value.zoneNumber,
      zoneType: selectedZone.value.zoneType,
      allowedHours: minutesToHours(selectedZone.value.allowedMinutes),
    };
    saveError.value = null;
  }

  function cancelEdit() {
    editDraft.value = null;
    saveError.value = null;
  }

  async function saveEdit() {
    if (!editDraft.value || !selectedZone.value) return;
    const zoneId = selectedZone.value.zoneId;
    const draft = editDraft.value;
    // 비워두면 ''(문자열)이라 Number('') === 0이 되어버리므로 별도로 걸러낸다.
    const hasAllowedHours = draft.allowedHours !== '' && !Number.isNaN(Number(draft.allowedHours));

    saving.value = true;
    saveError.value = null;
    try {
      const accessToken = authStore.accessToken;
      if (!accessToken) throw new Error('로그인이 필요합니다.');
      const updated = await updateZone(
        zoneId,
        {
          zoneNumber: draft.zoneNumber,
          zoneType: draft.zoneType,
          ...(hasAllowedHours ? { allowedMinutes: hoursToMinutes(Number(draft.allowedHours)) } : {}),
        },
        accessToken,
      );
      // ZoneResponse(PATCH 응답)에는 floor가 없어 기존 값을 그대로 두고 나머지 필드만 덮어쓴다.
      zones.value = zones.value.map((z) => (z.zoneId === zoneId ? { ...z, ...updated } : z));
      selectedZoneId.value = updated.zoneId;
      editDraft.value = null;
      await loadSummary(true);
    } catch (error) {
      saveError.value = error instanceof Error ? error.message : '구역 수정에 실패했습니다.';
    } finally {
      saving.value = false;
    }
  }

  return {
    FLOOR_KEYS,
    selectedFloor,
    zones,
    zonesLoading,
    zonesError,
    spots,
    summaryLoading,
    summaryError,
    typeFilter,
    statusFilter,
    codeQuery,
    selectedZoneId,
    editDraft,
    saveError,
    saving,
    occupancyOf,
    congestion,
    floorZones,
    zoneStats,
    filteredRows,
    selectedZone,
    selectZoneId,
    selectSpot,
    startEdit,
    cancelEdit,
    saveEdit,
  };
}
