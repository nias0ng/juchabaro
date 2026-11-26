import { Modal, Pressable, ScrollView, Text, View } from 'react-native';

import { ParkingLegend } from '@/features/parking/components/parking-legend';
import { ParkingSpotMap } from '@/features/parking/components/parking-spot-map';
import { useParkingZoneSummary } from '@/features/parking/hooks/use-parking-zone-summary';
import { toParkingStatusDisplay, type ParkingFloorKey } from '@/features/parking/utils/parking-zone';
import { useColorTokens } from '@/hooks/use-color-tokens';
import { useThemedStyles } from '@/hooks/use-themed-styles';

import { createStyles } from './request-compose-zone-picker-modal.styles';

type RequestComposeZonePickerModalProps = {
  visible: boolean;
  onClose: () => void;
  onSelectSpot: (spotCode: string) => void;
};

// 홈 화면 주차 현황 카드와 동일하게, 지금은 지하 1층 하나만 지원한다(구역 API에 층 정보가 없음).
const ZONE_FLOOR: ParkingFloorKey = 'B1';

/** "차량 구역"의 "선택"을 누르면 뜨는 팝업. 홈 화면 주차 현황 카드와 같은 실제 층 배치 지도에서 자리를 골라 고른다. */
export function RequestComposeZonePickerModal({ visible, onClose, onSelectSpot }: RequestComposeZonePickerModalProps) {
  const styles = useThemedStyles(createStyles);
  const t = useColorTokens();
  const { summary, isLoading, error } = useParkingZoneSummary();
  const status = summary ? toParkingStatusDisplay(summary, [], ZONE_FLOOR) : null;

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

          <ScrollView style={styles.scrollArea} contentContainerStyle={styles.scrollContent}>
            <ParkingSpotMap
              cells={status?.cells ?? []}
              message={message}
              onPressCell={onSelectSpot}
              floor={ZONE_FLOOR}
            />

            <ParkingLegend
              items={[
                { label: '주차 중', color: t.parkingMap.occupied },
                { label: '비어 있음', color: t.parkingMap.empty },
                { label: '충전구역', color: t.parkingMap.charging },
                { label: '장애인구역', color: t.parkingMap.accessible },
              ]}
            />
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}
