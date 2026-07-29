import type { ParkingSession } from './types';

const MOCK_RESPONSE_DELAY_MS = 500;

const mockSessions: ParkingSession[] = [
  {
    sessionId: 501,
    vehicleId: 10,
    plateNumber: '12가 3456',
    status: 'PARKED', // VIOLATION 으로 바꾸면 위반중으로 뜸
    zoneId: 3,
    zoneName: 'B1',
    spotCode: 'EV-01',
    enteredAt: new Date().toISOString(),
  },
];

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function getMyParkingSessionsMock(): Promise<ParkingSession[]> {
  await delay(MOCK_RESPONSE_DELAY_MS);
  return mockSessions;
}
