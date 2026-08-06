import { router } from 'expo-router';
import { Pressable, Text, View } from 'react-native';

import { FormErrorBanner, FormSectionLabel, ResponsiveContainer, Screen, ScreenHeader, Stack } from '@/components/ui';
import { Spacing } from '@/styles';

import { RequestComposePhotoPicker } from '../components/request-compose/request-compose-photo-picker';
import { RequestComposePlateCard } from '../components/request-compose/request-compose-plate-card';
import { RequestComposeReasonField } from '../components/request-compose/request-compose-reason-field';
import { RequestComposeSituationSelector } from '../components/request-compose/request-compose-situation-selector';
import { RequestComposeZonePickerModal } from '../components/request-compose/request-compose-zone-picker-modal';
import { RequestComposeZoneSelector } from '../components/request-compose/request-compose-zone-selector';
import { useRequestComposeForm } from '../hooks/use-request-compose-form';
import { styles } from './request-compose-screen.styles';

const BACKGROUND_GRADIENT = ['#f0edfb', '#f7f6fb'] as const;
const BACKGROUND_GRADIENT_LOCATIONS = [0, 0.4] as const;

export default function RequestComposeScreen() {
  const form = useRequestComposeForm();

  const handleSubmit = async () => {
    const result = await form.submit();
    if (!result) return;

    router.replace({
      pathname: '/resident/request-sent',
      params: {
        requestId: String(result.requestId),
        plateNumber: form.plateNumber,
        situationLabel: form.situation,
        requestedAtLabel: result.requestedAt,
      },
    });
  };

  return (
    <Screen
      scroll
      edges={['top', 'right', 'left']}
      backgroundGradient={BACKGROUND_GRADIENT}
      backgroundGradientLocations={BACKGROUND_GRADIENT_LOCATIONS}
    >
      <ResponsiveContainer style={styles.content}>
        <ScreenHeader title="이동 요청" onBack={() => router.back()} />

        <Stack gap={Spacing.lg}>
        <Stack gap={Spacing.xs + 3}>
          <FormSectionLabel label="차량 번호" />
          <RequestComposePlateCard plateNumber={form.plateNumber} onChangeText={form.setPlateNumber} />
        </Stack>

        <Stack gap={Spacing.xs + 3}>
          <FormSectionLabel label="차량 구역" />
          <RequestComposeZoneSelector zoneLabel={form.zoneLabel} onPress={form.openZonePicker} />
        </Stack>

        <Stack gap={Spacing.sm}>
          <FormSectionLabel label="어떤 상황인가요?" />
          <RequestComposeSituationSelector value={form.situation} onChange={form.setSituation} />
        </Stack>

        <Stack gap={Spacing.sm + 1}>
          <FormSectionLabel label="현장 사진" suffix={`${form.photos.length} / ${form.maxPhotos}`} />
          <RequestComposePhotoPicker
            photos={form.photos}
            maxPhotos={form.maxPhotos}
            onPressAdd={form.addPhoto}
            onRemove={form.removePhoto}
          />
        </Stack>

        <Stack gap={Spacing.sm + 1}>
          <FormSectionLabel label="요청 사유" />
          <RequestComposeReasonField
            value={form.reason}
            onChangeText={form.setReason}
            placeholder="ex. 출차 통로를 막고 있어 차량 이동을 요청합니다."
          />
        </Stack>
        </Stack>

        <View style={styles.footer}>
          {form.submitError ? <FormErrorBanner message={form.submitError} /> : null}

          <Text style={styles.privacyNotice}>요청자의 개인정보는 차주에게 공개되지 않습니다.</Text>

          <Pressable
            accessibilityRole="button"
            disabled={!form.canSubmit || form.isSubmitting}
            style={[styles.submitButton, (!form.canSubmit || form.isSubmitting) && styles.submitButtonDisabled]}
            onPress={handleSubmit}
          >
            <Text style={styles.submitButtonText}>{form.isSubmitting ? '전송 중...' : '요청 전송'}</Text>
          </Pressable>
        </View>
      </ResponsiveContainer>

      <RequestComposeZonePickerModal
        visible={form.isZonePickerOpen}
        onClose={form.closeZonePicker}
        onSelectSpot={form.selectZoneSpot}
      />
    </Screen>
  );
}
