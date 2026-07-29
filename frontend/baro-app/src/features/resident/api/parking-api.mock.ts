import type { ParkingSession, ParkingZoneSummary } from './types';

const MOCK_RESPONSE_DELAY_MS = 500;

const mockSessions: ParkingSession[] = [
  {
    sessionId: 501,
    vehicleId: 10,
    plateNumber: '12가 3456',
    status: 'PARKED', // VIOLATION 으로 바꾸면 위반중으로 뜸
    zoneId: 3,
    zoneName: 'B1',
    spotCode: 'A-01',
    enteredAt: new Date().toISOString(),
  },
];

const mockZoneSummary: ParkingZoneSummary = {
  totalSpots: 6,
  occupiedSpots: 3,
  availableSpots: 3,
  violationCount: 1,
  congestionRate: 50,
  congestionLevel: 'MEDIUM',
  spots: [
    { spotCode: 'EV-01', spotType: 'EV_CHARGING', status: 'EMPTY' },
    { spotCode: 'A-02', spotType: 'GENERAL', status: 'EMPTY' },
    { spotCode: 'A-03', spotType: 'GENERAL', status: 'VIOLATION' },
    { spotCode: 'A-04', spotType: 'DISABLED', status: 'EMPTY' },
    { spotCode: 'D-01', spotType: 'GENERAL', status: 'OCCUPIED' },
    { spotCode: 'A-01', spotType: 'GENERAL', status: 'OCCUPIED' }, // mockSessions의 spotCode와 동일 -> '내 차' 칸으로 표시됨
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
