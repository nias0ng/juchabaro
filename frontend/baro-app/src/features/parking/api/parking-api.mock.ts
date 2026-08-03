import type { ParkingSession, ParkingZoneSummary } from './types';

const MOCK_RESPONSE_DELAY_MS = 500;

const mockSessions: ParkingSession[] = [
  {
    sessionId: 501,
    vehicleId: 10,
    plateNumber: '12가 3456',
    status: 'PARKED', // VIOLATION 으로 바꾸면 위반중으로 뜸
    zoneId: 2,
    zoneNumber: 'A-01',
    floor: 'B1',
    enteredAt: new Date().toISOString(),
  },
];

const mockZoneSummary: ParkingZoneSummary = {
  floor: 'B1',
  totalSpots: 6,
  occupiedSpots: 3,
  availableSpots: 3,
  violationCount: 1,
  congestionRate: 50,
  congestionLevel: 'MEDIUM',
  spots: [
    {
      zoneId: 1,
      zoneNumber: 'EV-01',
      zoneType: 'EV_CHARGING',
      geometryData: null,
      occupancyStatus: 'EMPTY',
    },
    {
      zoneId: 3,
      zoneNumber: 'A-02',
      zoneType: 'GENERAL',
      geometryData: null,
      occupancyStatus: 'EMPTY',
    },
    {
      zoneId: 5,
      zoneNumber: 'A-03',
      zoneType: 'GENERAL',
      geometryData: null,
      occupancyStatus: 'VIOLATION',
    },
    {
      zoneId: 6,
      zoneNumber: 'A-04',
      zoneType: 'GENERAL',
      geometryData: null,
      occupancyStatus: 'EMPTY',
    },
    {
      zoneId: 4,
      zoneNumber: 'D-01',
      zoneType: 'DISABLED',
      geometryData: null,
      occupancyStatus: 'OCCUPIED',
    },
    {
      zoneId: 2,
      zoneNumber: 'A-01',
      zoneType: 'GENERAL',
      geometryData: null,
      occupancyStatus: 'OCCUPIED',
    }, // mockSessions의 zoneId/zoneNumber와 동일 -> '내 차' 칸으로 표시됨
  ],
};

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function getMyParkingSessionsMock(): Promise<ParkingSession[]> {
  await delay(MOCK_RESPONSE_DELAY_MS);
  return mockSessions;
}

export async function getParkingZoneSummaryMock(): Promise<ParkingZoneSummary> {
  await delay(MOCK_RESPONSE_DELAY_MS);
  return mockZoneSummary;
}
