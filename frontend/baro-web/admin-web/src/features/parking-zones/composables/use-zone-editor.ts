import { ref } from 'vue';
import type { ComputedRef, Ref } from 'vue';

import { updateZone } from '@/features/parking-zones/api/parking-zone-api';
import type { ZoneCatalogItem, ZoneType } from '@/features/parking-zones/api/types';
import { hoursToMinutes, minutesToHours } from '@/features/parking-zones/data';
import { useAuthStore } from '@/stores/auth-store';

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

// useZoneCatalog가 관리하는 상태 중, 구역 수정 흐름에 필요한 부분만 가져다 쓴다(구역
// 목록/필터/로딩 상태 전체를 알 필요가 없다).
type CatalogDeps = {
  selectedZone: ComputedRef<ZoneCatalogItem | null>;
  zones: Ref<ZoneCatalogItem[]>;
  selectedZoneId: Ref<number | null>;
  loadSummary: (background?: boolean) => Promise<void>;
};

// 선택된 구역의 수정 draft·저장 흐름만 담당한다. 어떤 구역이 선택되어 있는지, 구역 목록을
// 어떻게 다시 불러오는지는 use-zone-catalog.ts가 책임진다.
export function useZoneEditor(catalog: CatalogDeps) {
  const authStore = useAuthStore();

  const editDraft = ref<EditDraft | null>(null);
  const saveError = ref<string | null>(null);
  const saving = ref(false);

  function resetDraft() {
    editDraft.value = null;
    saveError.value = null;
  }

  function startEdit() {
    const zone = catalog.selectedZone.value;
    if (!zone) return;
    editDraft.value = {
      zoneNumber: zone.zoneNumber,
      zoneType: zone.zoneType,
      allowedHours: minutesToHours(zone.allowedMinutes),
    };
    saveError.value = null;
  }

  function cancelEdit() {
    resetDraft();
  }

  async function saveEdit() {
    const zone = catalog.selectedZone.value;
    if (!editDraft.value || !zone) return;
    const zoneId = zone.zoneId;
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
      catalog.zones.value = catalog.zones.value.map((z) => (z.zoneId === zoneId ? { ...z, ...updated } : z));
      catalog.selectedZoneId.value = updated.zoneId;
      editDraft.value = null;
      await catalog.loadSummary(true);
    } catch (error) {
      saveError.value = error instanceof Error ? error.message : '구역 수정에 실패했습니다.';
    } finally {
      saving.value = false;
    }
  }

  return {
    editDraft,
    saveError,
    saving,
    startEdit,
    cancelEdit,
    saveEdit,
    resetDraft,
  };
}
