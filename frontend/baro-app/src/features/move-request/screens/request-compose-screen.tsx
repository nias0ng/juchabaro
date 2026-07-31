import { router } from 'expo-router';
import { Pressable, Text, View } from 'react-native';

import { Screen, ScreenHeader, Stack } from '@/components/ui';
import { Spacing } from '@/styles';

import { RequestComposePhotoPicker } from '../components/request-compose/request-compose-photo-picker';
import { RequestComposePlateCard } from '../components/request-compose/request-compose-plate-card';
import { RequestComposeReasonField } from '../components/request-compose/request-compose-reason-field';
import { RequestComposeSectionLabel } from '../components/request-compose/request-compose-section-label';
import { RequestComposeSituationSelector } from '../components/request-compose/request-compose-situation-selector';
import { RequestComposeZonePickerModal } from '../components/request-compose/request-compose-zone-picker-modal';
import { RequestComposeZoneSelector } from '../components/request-compose/request-compose-zone-selector';
import { useRequestComposeForm } from '../hooks/use-request-compose-form';
import { styles } from './request-compose-screen.styles';

const BACKGROUND_GRADIENT = ['#f0edfb', '#f7f6fb'] as const;
const BACKGROUND_GRADIENT_LOCATIONS = [0, 0.4] as const;

export default function RequestComposeScreen() {
  const form = useRequestComposeForm();

  return (
    <Screen
      scroll
      edges={['top', 'right', 'left']}
      backgroundGradient={BACKGROUND_GRADIENT}
      backgroundGradientLocations={BACKGROUND_GRADIENT_LOCATIONS}
      contentContainerStyle={styles.content}
    >
      <ScreenHeader title="이동 요청" onBack={() => router.back()} />

      <Stack gap={Spacing.lg}>
        <Stack gap={Spacing.xs + 3}>
          <RequestComposeSectionLabel label="차량 번호" />
          <RequestComposePlateCard plateNumber={form.plateNumber} onChangeText={form.setPlateNumber} />
        </Stack>

        <Stack gap={Spacing.xs + 3}>
          <RequestComposeSectionLabel label="차량 구역" />
          <RequestComposeZoneSelector zoneLabel={form.zoneLabel} onPress={form.openZonePicker} />
        </Stack>

        <Stack gap={Spacing.sm}>
          <RequestComposeSectionLabel label="어떤 상황인가요?" />
          <RequestComposeSituationSelector value={form.situation} onChange={form.setSituation} />
        </Stack>

        <Stack gap={Spacing.sm + 1}>
          <RequestComposeSectionLabel label="현장 사진" suffix={`${form.photos.length} / ${form.maxPhotos}`} />
          <RequestComposePhotoPicker
            photos={form.photos}
            maxPhotos={form.maxPhotos}
            onPressAdd={form.addPhoto}
            onRemove={form.removePhoto}
          />
        </Stack>

        <Stack gap={Spacing.sm + 1}>
          <RequestComposeSectionLabel label="요청 사유" />
          <RequestComposeReasonField value={form.reason} onChangeText={form.setReason} />
        </Stack>
      </Stack>

      <View style={styles.footer}>
        <Text style={styles.privacyNotice}>요청자의 개인정보는 차주에게 공개되지 않습니다.</Text>

        {/* TODO(request-compose): POST /move-requests 연동 전까지는 전송 동작이 없다. */}
        <Pressable accessibilityRole="button" style={styles.submitButton}>
          <Text style={styles.submitButtonText}>요청 전송</Text>
        </Pressable>
      </View>

      <RequestComposeZonePickerModal
        visible={form.isZonePickerOpen}
        onClose={form.closeZonePicker}
        onSelectSpot={form.selectZoneSpot}
      />
    </Screen>
  );
}
