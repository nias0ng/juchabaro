import { Modal, Pressable, Text, View } from 'react-native';

import { ParkingLegend } from '@/features/parking/components/parking-legend';
import { ParkingSpotMap } from '@/features/parking/components/parking-spot-map';
import { useParkingZoneSummary } from '@/features/parking/hooks/use-parking-zone-summary';
import { toParkingStatusDisplay } from '@/features/parking/utils/parking-zone';
import { Palette } from '@/styles';

import { styles } from './request-compose-zone-picker-modal.styles';

type RequestComposeZonePickerModalProps = {
  visible: boolean;
  onClose: () => void;
  onSelectSpot: (spotCode: string) => void;
};

/** "차량 구역"의 "선택"을 누르면 뜨는 팝업. 홈 화면 주차 현황 카드와 같은 지도에서 자리를 골라 고른다. */
export function RequestComposeZonePickerModal({ visible, onClose, onSelectSpot }: RequestComposeZonePickerModalProps) {
  const { summary, isLoading, error } = useParkingZoneSummary();
  const status = summary ? toParkingStatusDisplay(summary, []) : null;

  const message = isLoading
    ? '주차 현황을 불러오는 중입니다'
    : error
      ? '주차 현황을 불러오지 못했습니다'
      : !status
        ? '표시할 주차 현황이 없습니다'
        : undefined;

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.overlay}>
        <View style={styles.sheet}>
          <View style={styles.headerRow}>
            <Text style={styles.title}>구역 선택</Text>
            <Pressable accessibilityRole="button" accessibilityLabel="닫기" hitSlop={8} onPress={onClose}>
              <Text style={styles.closeIcon}>✕</Text>
            </Pressable>
          </View>

          <Text style={styles.subtitle}>차량이 있는 자리를 눌러 주세요.</Text>

          <ParkingSpotMap cells={status?.cells ?? []} message={message} onPressCell={onSelectSpot} />

          <ParkingLegend
            items={[
              { label: '주차 중', color: Palette.violet300 },
              { label: '비어 있음', color: Palette.gray100 },
              { label: '충전구역', color: Palette.teal100 },
              { label: '장애인구역', color: Palette.sky100 },
            ]}
          />
        </View>
      </View>
    </Modal>
  );
}
