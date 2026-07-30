import { Stack } from '@/components/ui';
import { Spacing } from '@/styles';

import type { VehicleResult } from '@/features/auth/api/vehicle-types';

import { VehicleCard } from './vehicle-card';

type VehicleListProps = {
  vehicles: VehicleResult[];
  onDeleteVehicle: (vehicle: VehicleResult) => void;
};

/** H-02-1(1대)/H-02-2(2대 이상)에서 등록된 차량 목록을 보여준다. */
export function VehicleList({ vehicles, onDeleteVehicle }: VehicleListProps) {
  return (
    <Stack gap={Spacing.md}>
      {vehicles.map((vehicle) => (
        <VehicleCard key={vehicle.vehicleId} vehicle={vehicle} onDelete={onDeleteVehicle} />
      ))}
    </Stack>
  );
}
