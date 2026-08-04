import { getJson, patchJson, postJson } from '@/services/http-client';

import type {
  ParkingZoneSummaryResult,
  ZoneCatalogResult,
  ZoneImportRequest,
  ZoneImportResult,
  ZoneResponse,
  ZoneUpdateRequest,
} from './types';

export function getZones(accessToken: string): Promise<ZoneCatalogResult> {
  return getJson<ZoneCatalogResult>('/api/zones', accessToken);
}

export function getParkingZoneSummary(accessToken: string): Promise<ParkingZoneSummaryResult> {
  return getJson<ParkingZoneSummaryResult>('/api/parking-zones/summary', accessToken);
}

export function updateZone(zoneId: number, request: ZoneUpdateRequest, accessToken: string): Promise<ZoneResponse> {
  return patchJson<ZoneResponse>(`/api/zones/${zoneId}`, request, accessToken);
}

// HW 캘리브레이션 도구가 zone_definition을 올릴 때 쓰는 API. 관리자 화면에는 수동 입력
// 버튼을 두지 않았고, 이 함수는 향후 필요할 때를 위해 계약만 맞춰 둔다.
export function importZones(request: ZoneImportRequest, accessToken: string): Promise<ZoneImportResult> {
  return postJson<ZoneImportResult>('/api/zones/import', request, accessToken);
}
