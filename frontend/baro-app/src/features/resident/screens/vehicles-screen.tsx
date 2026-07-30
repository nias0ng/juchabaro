import { router } from 'expo-router';
import { View } from 'react-native';

import { ResponsiveContainer, Screen, Stack, ThemedText } from '@/components/ui';
import { Spacing } from '@/styles';

import { VehicleAddSection } from '../components/manageCar/vehicle-add-section';
import { VehicleDeleteConfirmModal } from '../components/manageCar/vehicle-delete-confirm-modal';
import { VehicleEmptyState } from '../components/manageCar/vehicle-empty-state';
import { VehicleErrorState } from '../components/manageCar/vehicle-error-state';
import { VehicleList } from '../components/manageCar/vehicle-list';
import { VehicleLoadingState } from '../components/manageCar/vehicle-loading-state';
import { useVehicleManagement } from '../hooks/use-vehicle-management';

import { styles } from './vehicles-screen.styles';

/**
 * H-01(0대)/H-02-1(1대)/H-02-2(2대 이상)을 차량 개수에 따라 이 화면 하나에서 렌더링한다.
 * 화면이나 route를 나누지 않고, 조회 상태(status)와 vehicles 배열만으로 분기한다.
 */
export default function VehiclesScreen() {
  const vehicleManagement = useVehicleManagement();
  const { status, vehicles, listErrorMessage, refetch } = vehicleManagement;

  const handleAddVehicle = () => {
    router.push('/auth/register-car');
  };

  return (
    <View style={styles.flex}>
      <Screen scroll edges={['top', 'right', 'left']}>
        <ResponsiveContainer>
          <Stack gap={Spacing.xl}>
            <ThemedText type="subtitle">차량 관리</ThemedText>

            {status === 'loading' && <VehicleLoadingState />}

            {status === 'error' && (
              <VehicleErrorState
                message={listErrorMessage ?? '차량 목록을 불러오지 못했습니다.'}
                onRetry={refetch}
              />
            )}

            {status === 'success' && vehicles.length === 0 && (
              <VehicleEmptyState onAddVehicle={handleAddVehicle} />
            )}

            {status === 'success' && vehicles.length > 0 && (
              <Stack gap={Spacing.md}>
                <VehicleList vehicles={vehicles} onDeleteVehicle={vehicleManagement.openDeleteModal} />
                <VehicleAddSection onPress={handleAddVehicle} />
              </Stack>
            )}
          </Stack>
        </ResponsiveContainer>
      </Screen>

      <VehicleDeleteConfirmModal
        visible={vehicleManagement.deleteTargetVehicle !== null}
        vehicle={vehicleManagement.deleteTargetVehicle}
        isDeleting={vehicleManagement.isDeleting}
        errorMessage={vehicleManagement.deleteErrorMessage}
        onCancel={vehicleManagement.closeDeleteModal}
        onConfirm={vehicleManagement.confirmDelete}
      />
    </View>
  );
}
