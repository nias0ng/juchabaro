import { watch } from 'vue';

import type { ParkingSpotSummary } from '@/features/parking-zones/api/types';

import { useZoneCatalog } from './use-zone-catalog';
import { useZoneEditor } from './use-zone-editor';

// useZoneCatalog(구역 목록·현황 데이터, 필터, 선택)와 useZoneEditor(선택된 구역 수정)를
// 조합한다. 층을 바꾸거나 다른 구역을 고르면 진행 중이던 편집 draft를 지워야 하는데, 이건
// 두 composable의 상태를 모두 건드리는 일이라 이 오케스트레이션 레이어에서 담당한다.
export function useZoneManagement() {
  const catalog = useZoneCatalog();
  const editor = useZoneEditor(catalog);

  watch(catalog.selectedFloor, () => editor.resetDraft());

  function selectZoneId(zoneId: number) {
    catalog.selectZoneId(zoneId);
    editor.resetDraft();
  }

  function selectSpot(spot: ParkingSpotSummary) {
    selectZoneId(spot.zoneId);
  }

  return {
    FLOOR_KEYS: catalog.FLOOR_KEYS,
    selectedFloor: catalog.selectedFloor,
    zonesLoading: catalog.zonesLoading,
    zonesError: catalog.zonesError,
    spots: catalog.spots,
    summaryLoading: catalog.summaryLoading,
    summaryError: catalog.summaryError,
    typeFilter: catalog.typeFilter,
    statusFilter: catalog.statusFilter,
    codeQuery: catalog.codeQuery,
    occupancyOf: catalog.occupancyOf,
    congestion: catalog.congestion,
    zoneStats: catalog.zoneStats,
    filteredRows: catalog.filteredRows,
    selectedZone: catalog.selectedZone,
    editDraft: editor.editDraft,
    saveError: editor.saveError,
    saving: editor.saving,
    startEdit: editor.startEdit,
    cancelEdit: editor.cancelEdit,
    saveEdit: editor.saveEdit,
    selectZoneId,
    selectSpot,
  };
}
