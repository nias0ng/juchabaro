import { router } from 'expo-router';
import { Text, View } from 'react-native';

import { ResponsiveContainer, Screen, ScreenHeader } from '@/components/ui';

import { VehicleAddCard } from '../components/management/vehicle-add-card';
import { VehicleDeleteConfirmModal } from '../components/management/vehicle-delete-confirm-modal';
import { VehicleErrorState } from '../components/management/vehicle-error-state';
import { VehicleList } from '../components/management/vehicle-list';
import { VehicleLoadingState } from '../components/management/vehicle-loading-state';
import { useVehicleManagement } from '../hooks/use-vehicle-management';

import { VEHICLES_SCREEN_BACKGROUND, styles } from './vehicles-screen.styles';

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
      <Screen scroll edges={['top', 'right', 'left']} backgroundColor={VEHICLES_SCREEN_BACKGROUND}>
        <ResponsiveContainer>
          <ScreenHeader title="내 차량 관리" onBack={() => router.back()} />

          <View style={styles.content}>
            {status === 'loading' && <VehicleLoadingState />}

            {status === 'error' && (
              <VehicleErrorState
                message={listErrorMessage ?? '차량 목록을 불러오지 못했습니다.'}
                onRetry={refetch}
              />
            )}

            {status === 'success' && (
              <>
                <View style={styles.countRow}>
                  <Text style={styles.countText}>{`등록된 차량 (${vehicles.length})`}</Text>
                </View>

                {vehicles.length > 0 && (
                  <VehicleList vehicles={vehicles} onDeleteVehicle={vehicleManagement.openDeleteModal} />
                )}

                <VehicleAddCard onPress={handleAddVehicle} />

                <Text style={styles.notice}>
                  {'부정확한 정보 입력 시 주차 서비스 이용에 제한될 수 있습니다.'}
                </Text>
              </>
            )}
          </View>
        </ResponsiveContainer>
      </Screen>

      <VehicleDeleteConfirmModal
        visible={vehicleManagement.deleteTargetVehicle !== null}
        isDeleting={vehicleManagement.isDeleting}
        errorMessage={vehicleManagement.deleteErrorMessage}
        onCancel={vehicleManagement.closeDeleteModal}
        onConfirm={vehicleManagement.confirmDelete}
      />
    </View>
  );
}
