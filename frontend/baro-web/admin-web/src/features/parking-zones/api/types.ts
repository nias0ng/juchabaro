// 구역(주차 구역) 관련 API의 요청/응답 타입. Notion API 명세서(S15P11E202)의
// "구역 카탈로그 조회", "주차 구역 현황 조회", "구역 수정", "구역 정의 import" 기준.

export type ZoneType = 'GENERAL' | 'DISABLED' | 'EV_CHARGING' | 'AISLE' | 'ENTRY_EXIT';

export type EntryExitRole = 'ENTRY' | 'EXIT';

// 명세에 ACTIVE만 확인됨(구역 자체의 운영 상태, 점유 여부와는 다른 필드).
export type ZoneStatus = 'ACTIVE';

export type OccupancyStatus = 'EMPTY' | 'OCCUPIED' | 'VIOLATION';

export type CongestionLevel = 'LOW' | 'MEDIUM' | 'HIGH';

export type ZoneGeometry = {
  coordSystem: string;
  polygon: number[][];
  chargerClass?: string | null;
  egressZoneIds?: number[] | null;
};

// GET /api/zones
export type ZoneCatalogItem = {
  zoneId: number;
  zoneNumber: string;
  hwZoneId: number | null;
  zoneType: ZoneType;
  entryExitRole: EntryExitRole | null;
  allowedMinutes: number | null;
  floor: string | null;
  status: ZoneStatus;
  geometry: ZoneGeometry | null;
};

export type ZoneCatalogResult = {
  totalCount: number;
  zones: ZoneCatalogItem[];
};

// GET /api/parking-zones/summary — 주차장은 지하 1층(B1)으로 고정되어 있다.
export type ParkingSpotSummary = {
  zoneId: number;
  zoneNumber: string;
  zoneType: ZoneType;
  geometryData: ZoneGeometry | null;
  occupancyStatus: OccupancyStatus;
};

export type ParkingZoneSummaryResult = {
  floor: string;
  totalSpots: number;
  occupiedSpots: number;
  availableSpots: number;
  violationCount: number;
  congestionRate: number;
  congestionLevel: CongestionLevel;
  spots: ParkingSpotSummary[];
};

// PATCH /api/zones/{zoneId} — 보낸 필드만 반영(부분 수정)
export type ZoneUpdateRequest = {
  zoneNumber?: string;
  zoneType?: ZoneType;
  allowedMinutes?: number;
};

export type ZoneResponse = {
  zoneId: number;
  zoneNumber: string;
  hwZoneId: number | null;
  zoneType: ZoneType;
  entryExitRole: EntryExitRole | null;
  allowedMinutes: number | null;
  status: ZoneStatus;
  geometry: ZoneGeometry | null;
};

// POST /api/zones/import — HW zone_definition upsert. 캘리브레이션 도구가 보내는 원시
// 좌표 데이터를 그대로 반영하는 용도라 관리자가 손으로 채우는 화면 입력이 아니다.
export type ZoneImportZoneItem = {
  zoneId: number;
  zoneType: ZoneType;
  entryExitRole?: EntryExitRole;
  allowedDurationSeconds?: number;
  polygon: number[][];
  chargerClass?: string;
  egressZoneIds?: number[];
};

export type ZoneImportRequest = {
  zoneDefinitionVersion: number;
  calibrationReference?: string;
  floor?: string;
  zones: ZoneImportZoneItem[];
};

export type ZoneImportResult = {
  total: number;
  created: number;
  updated: number;
};
