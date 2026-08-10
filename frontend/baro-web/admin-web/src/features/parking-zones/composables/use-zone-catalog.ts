import { computed, ref, watch } from 'vue';

import { useAutoRefresh } from '@/composables/use-auto-refresh';
import { getParkingZoneSummary, getZones } from '@/features/parking-zones/api/parking-zone-api';
import type { OccupancyStatus, ParkingSpotSummary, ZoneCatalogItem, ZoneType } from '@/features/parking-zones/api/types';
import {
  compareZoneNumbers,
  computeFloorCongestion,
  findSpotSummary,
  zoneFloorOf,
} from '@/features/parking-zones/data';
import type { FloorKey } from '@/features/parking-zones/types';
import { useAuthStore } from '@/stores/auth-store';

// B1의 실제 물리 배치를 그대로 복제해 B2/B3에도 등록해 뒀다(features/parking-zones/data.ts의
// floorZoneLayout 참고).
const FLOOR_KEYS: FloorKey[] = ['B1', 'B2', 'B3'];

// 구역 목록·주차 현황 데이터 로딩(요청 경합 가드 포함)과 층·유형·상태·검색 필터, 구역 선택을
// 담당한다. 구역 수정(편집 draft/저장)은 use-zone-editor.ts로 분리했다 — 이 파일이 238줄까지
// 커졌을 때 "데이터 조회"와 "수정 폼"이라는 서로 다른 책임이 한 파일에 섞여 있었기 때문이다.
export function useZoneCatalog() {
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
  // 구역 목록 전용 층 필터. null이면 "전체"(모든 층)를 보여준다. 특정 층을 고르면 지도 쪽
  // 층 탭(selectedFloor)도 같이 그 층으로 바뀐다(selectFloor 참고).
  const zoneFloorFilter = ref<FloorKey | null>(selectedFloor.value);
  const codeQuery = ref('');
  const selectedZoneId = ref<number | null>(null);

  function selectFloor(floor: FloorKey | null) {
    zoneFloorFilter.value = floor;
    if (floor) selectedFloor.value = floor;
  }

  function occupancyOf(zoneId: number): OccupancyStatus | null {
    return findSpotSummary(spots.value, zoneId)?.occupancyStatus ?? null;
  }

  // GET /api/parking-zones/summary가 층 구분 없이 전체를 한 번에 반환하기 때문에, 혼잡도는
  // 응답 최상위 값 대신 선택한 층의 구역만 걸러서 화면에서 직접 계산한다.
  const congestion = computed(() => computeFloorCongestion(selectedFloor.value, spots.value));

  // "전체 구역" 등 라벨이 실제로 전체를 뜻하므로, 선택한 층이 아니라 건물 전체 구역 기준으로 센다.
  const zoneStats = computed(() => ({
    total: zones.value.length,
    general: zones.value.filter((z) => z.zoneType === 'GENERAL').length,
    disabled: zones.value.filter((z) => z.zoneType === 'DISABLED').length,
    ev: zones.value.filter((z) => z.zoneType === 'EV_CHARGING').length,
  }));

  // 구역 목록은 zoneFloorFilter를 따른다 — null(전체)이면 모든 층, 아니면 그 층만.
  const floorZones = computed(() => {
    const sorted = zones.value.slice().sort((a, b) => compareZoneNumbers(a.zoneNumber, b.zoneNumber));
    if (!zoneFloorFilter.value) return sorted;
    return sorted.filter((z) => zoneFloorOf(z.zoneNumber) === zoneFloorFilter.value);
  });

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

  const hasActiveFilters = computed(
    () =>
      zoneFloorFilter.value !== null
      || typeFilter.value !== null
      || statusFilter.value !== null
      || codeQuery.value.trim() !== '',
  );

  // 지도 쪽 층(selectedFloor)은 그대로 두고, 목록 필터만 초기 상태(전체)로 되돌린다.
  function resetFilters() {
    zoneFloorFilter.value = null;
    typeFilter.value = null;
    statusFilter.value = null;
    codeQuery.value = '';
  }

  // 층 탭을 바꾸면 이전 층에서 고르던 구역 선택을 초기화해, 다른 층 이름의 구역이 그대로
  // "선택 구역 정보"에 남아있지 않게 한다(편집 draft 초기화는 use-zone-management.ts에서
  // 별도로 처리 — 이 composable은 편집 상태를 모른다). 다만 selectZoneId가 구역 목록 클릭에
  // 맞춰 층까지 같이 바꿔준 경우에는(아래) 그 구역이 이미 새 층 소속이라 초기화하지 않는다.
  watch(selectedFloor, () => {
    const zone = zones.value.find((z) => z.zoneId === selectedZoneId.value);
    if (!zone || zoneFloorOf(zone.zoneNumber) !== selectedFloor.value) {
      selectedZoneId.value = null;
    }
  });

  // 구역 목록에서 다른 층의 구역을 클릭하면 지도 쪽 층 탭도 그 층으로 같이 바뀐다.
  function selectZoneId(zoneId: number) {
    selectedZoneId.value = zoneId;
    const zone = zones.value.find((z) => z.zoneId === zoneId);
    const floor = zone ? zoneFloorOf(zone.zoneNumber) : null;
    if (floor) selectedFloor.value = floor;
  }

  function selectSpot(spot: ParkingSpotSummary) {
    selectZoneId(spot.zoneId);
  }

  return {
    FLOOR_KEYS,
    selectedFloor,
    zoneFloorFilter,
    selectFloor,
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
    occupancyOf,
    congestion,
    zoneStats,
    filteredRows,
    hasActiveFilters,
    resetFilters,
    selectedZone,
    selectZoneId,
    selectSpot,
    loadSummary,
  };
}
