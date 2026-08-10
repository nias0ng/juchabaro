import { router, useLocalSearchParams } from 'expo-router';
import { Pressable, Text, View } from 'react-native';

import { InfoRowCard, ResponsiveContainer, Screen } from '@/components/ui';

import { RequestCheckBadge } from '../components/request-check-badge';
import { formatTime24 } from '../utils/move-request';
import { styles } from './request-sent-screen.styles';

const BACKGROUND_GRADIENT = ['#eae7fb', '#f7f6fb'] as const;
const BACKGROUND_GRADIENT_LOCATIONS = [0, 0.5] as const;

export default function RequestSentScreen() {
  const params = useLocalSearchParams<{
    requestId: string;
    plateNumber: string;
    situationLabel: string;
    requestedAtLabel: string;
  }>();

  const requestedAtLabel = params.requestedAtLabel ? formatTime24(params.requestedAtLabel) : '--:--';

  const handleViewStatus = () => {
    if (!params.requestId) return;
    router.replace({ pathname: '/resident/request-detail', params: { requestId: params.requestId } });
  };

  return (
    <Screen
      scroll
      edges={['top', 'right', 'left']}
      backgroundGradient={BACKGROUND_GRADIENT}
      backgroundGradientLocations={BACKGROUND_GRADIENT_LOCATIONS}
    >
      <ResponsiveContainer style={styles.content}>
        <RequestCheckBadge outerSize={96} innerSize={38} />

        <Text style={styles.title}>{'이동 요청을\n전송했습니다'}</Text>
        <Text style={styles.subtitle}>
          {'차주에게 알림이 전달되었습니다.\n응답이 오면 바로 알려드리겠습니다.'}
        </Text>

        <View style={styles.summaryMargin}>
          <InfoRowCard
            rows={[
              { label: '대상 차량', value: params.plateNumber ?? '-' },
              { label: '상황', value: params.situationLabel ?? '-' },
              { label: '요청 시각', value: requestedAtLabel },
            ]}
          />
        </View>

        <View style={styles.actions}>
          <Pressable accessibilityRole="button" style={styles.primaryButton} onPress={handleViewStatus}>
            <Text style={styles.primaryButtonText}>요청 상태 보기</Text>
          </Pressable>

          <Pressable accessibilityRole="button" style={styles.secondaryButton} onPress={() => router.replace('/resident')}>
            <Text style={styles.secondaryButtonText}>홈으로</Text>
          </Pressable>
        </View>
      </ResponsiveContainer>
    </Screen>
  );
}
