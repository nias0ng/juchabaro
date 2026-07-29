export type ParkingSessionStatus = 'PARKED' | 'VIOLATION';

export type ParkingSession = {
  sessionId: number;
  vehicleId: number;
  plateNumber: string;
  status: ParkingSessionStatus;
  zoneId: number;
  zoneName: string;
  spotCode: string;
  enteredAt: string; // ISO 8601
};
