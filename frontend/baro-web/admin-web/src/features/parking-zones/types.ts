export type {
  CongestionLevel,
  EntryExitRole,
  OccupancyStatus,
  ParkingSpotSummary,
  ZoneCatalogItem,
  ZoneStatus,
  ZoneType,
} from './api/types';

export type CellVariant = 'empty' | 'occupied' | 'violation' | 'disabled' | 'ev';

// 실제로 점유 현황이 연결된 층(B1) + B2/B3처럼 같은 물리 배치를 그대로 복제해 등록한 층.
export type FloorKey = 'B1' | 'B2' | 'B3';
