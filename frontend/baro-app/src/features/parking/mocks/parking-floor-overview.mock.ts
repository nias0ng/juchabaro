import type { ParkingSession, ParkingZoneType } from '../api/types';

export type MockSpotStatus = 'OCCUPIED' | 'EMPTY' | 'VIOLATION' | 'MINE';

export type MockParkingSpot = {
  spotCode: string;
  status: MockSpotStatus;
  spotType: ParkingZoneType;
};

export type ParkingFloorKey = 'b1' | 'b2' | 'b3';

// 자리(배열 인덱스=그리드 위치)는 항상 고정한다. 특정 자리의 주차 칸을 없애고 싶으면
// 해당 spot(...) 줄을 지우지 말고 null로 바꾼다 — 그러면 뒤 칸들이 당겨지지 않고
// 그 자리만 빈 배경으로 남는다.
export type MockParkingFloor = {
  key: ParkingFloorKey;
  label: string;
  spots: (MockParkingSpot | null)[];
  /** 그리드 오른쪽의 가로형 칸 한 줄. 행 개수(6)와 같은 개수로 맞춘다. */
  sideSpots: (MockParkingSpot | null)[];
};

export type MockMyVehicleLocation = {
  floorKey: ParkingFloorKey;
  title: string;
  description: string;
};

function spot(
  spotCode: string,
  status: MockSpotStatus,
  spotType: ParkingZoneType = 'GENERAL',
): MockParkingSpot {
  return { spotCode, status, spotType };
}

// TODO: GET /api/parking-zones/summary에 층(floor) 개념이 추가되면 이 배열을 실제 응답 데이터로 교체한다.
export const MOCK_PARKING_FLOORS: MockParkingFloor[] = [
  {
    key: 'b1',
    label: '지하 1층',
    spots: [
      spot('B1-01', 'OCCUPIED'),
      spot('B1-02', 'VIOLATION'),
      spot('B1-03', 'OCCUPIED'),
      spot('B1-04', 'OCCUPIED'),
      spot('B1-05', 'OCCUPIED'),
      spot('B1-06', 'EMPTY'),
      spot('B1-07', 'OCCUPIED'),
      spot('B1-08', 'OCCUPIED'),
      spot('B1-09', 'EMPTY'),
      spot('B1-10', 'OCCUPIED'),
      spot('B1-11', 'EMPTY'),
      spot('B1-12', 'OCCUPIED'),
      spot('B1-13', 'EMPTY'),
      spot('B1-14', 'OCCUPIED'),
      spot('B1-15', 'EMPTY'),
      spot('B1-16', 'OCCUPIED'),
      spot('B1-EV1', 'OCCUPIED', 'EV_CHARGING'),
      spot('B1-EV2', 'OCCUPIED', 'EV_CHARGING'),
      spot('B1-17', 'EMPTY'),
      spot('B1-18', 'VIOLATION'),
      spot('B1-D1', 'OCCUPIED', 'DISABLED'),
      spot('B1-D2', 'OCCUPIED', 'DISABLED'),
      spot('B1-19', 'OCCUPIED'),
      spot('B1-20', 'MINE'),
    ],
    sideSpots: [
      spot('B1-S1', 'OCCUPIED'),
      spot('B1-S2', 'EMPTY'),
      spot('B1-S3', 'OCCUPIED'),
      spot('B1-S4', 'OCCUPIED'),
      null,
      null,
    ],
  },
  {
    key: 'b2',
    label: '지하 2층',
    spots: [
      spot('B2-01', 'OCCUPIED'),
      spot('B2-02', 'EMPTY'),
      spot('B2-03', 'OCCUPIED'),
      spot('B2-04', 'EMPTY'),
      spot('B2-05', 'EMPTY'),
      spot('B2-06', 'OCCUPIED'),
      spot('B2-07', 'EMPTY'),
      spot('B2-08', 'OCCUPIED'),
      spot('B2-09', 'EMPTY'),
      spot('B2-10', 'EMPTY'),
      spot('B2-11', 'OCCUPIED'),
      spot('B2-12', 'EMPTY'),
      spot('B2-13', 'OCCUPIED'),
      spot('B2-14', 'EMPTY'),
      spot('B2-15', 'OCCUPIED'),
      spot('B2-16', 'EMPTY'),
      spot('B2-EV1', 'EMPTY', 'EV_CHARGING'),
      spot('B2-EV2', 'EMPTY', 'EV_CHARGING'),
      spot('B2-17', 'OCCUPIED'),
      spot('B2-18', 'EMPTY'),
      spot('B2-D1', 'EMPTY', 'DISABLED'),
      spot('B2-D2', 'OCCUPIED', 'DISABLED'),
      spot('B2-19', 'EMPTY'),
      spot('B2-20', 'OCCUPIED'),
    ],
    sideSpots: [
      spot('B2-S1', 'OCCUPIED'),
      spot('B2-S2', 'OCCUPIED'),
      spot('B2-S3', 'VIOLATION'),
      spot('B2-S4', 'VIOLATION'),
      spot('B2-S5', 'EMPTY'),
      spot('B2-S6', 'OCCUPIED'),
    ],
  },
  {
    key: 'b3',
    label: '지하 3층',
    spots: [
      spot('B3-01', 'EMPTY'),
      spot('B3-02', 'EMPTY'),
      spot('B3-03', 'OCCUPIED'),
      spot('B3-04', 'EMPTY'),
      spot('B3-05', 'OCCUPIED'),
      spot('B3-06', 'EMPTY'),
      spot('B3-07', 'EMPTY'),
      spot('B3-08', 'OCCUPIED'),
      spot('B3-09', 'EMPTY'),
      spot('B3-10', 'EMPTY'),
      spot('B3-11', 'OCCUPIED'),
      spot('B3-12', 'EMPTY'),
      spot('B3-13', 'EMPTY'),
      spot('B3-14', 'OCCUPIED'),
      spot('B3-15', 'EMPTY'),
      spot('B3-16', 'EMPTY'),
      spot('B3-EV1', 'OCCUPIED', 'EV_CHARGING'),
      spot('B3-EV2', 'EMPTY', 'EV_CHARGING'),
      spot('B3-17', 'EMPTY'),
      spot('B3-18', 'OCCUPIED'),
      spot('B3-D2', 'EMPTY', 'DISABLED'),
      spot('B3-D1', 'EMPTY', 'DISABLED'),
      spot('B3-19', 'EMPTY'),
      spot('B3-20', 'EMPTY'),
    ],
    sideSpots: [
      spot('B3-S1', 'EMPTY'),
      spot('B3-S2', 'OCCUPIED'),
      spot('B3-S3', 'EMPTY'),
      spot('B3-S4', 'EMPTY'),
      spot('B3-S5', 'EMPTY'),
      spot('B3-S6', 'EMPTY'),
    ],
  },
];

export function getMyVehicleLocation(
  sessions: ParkingSession[],
): MockMyVehicleLocation | null {
  const session = sessions.find(({ status }) => status === 'PARKED');
  if (!session) return null;

  const floorKey = session.floor.trim().toLowerCase();
  if (!MOCK_PARKING_FLOORS.some(({ key }) => key === floorKey)) return null;

  return {
    floorKey: floorKey as ParkingFloorKey,
    title: `내 차량 · ${session.zoneNumber}`,
    description: `${session.floor} · ${session.plateNumber}`,
  };
}
