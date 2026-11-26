import { router, useLocalSearchParams } from 'expo-router';
import { Pressable, Text, View } from 'react-native';

import { InfoRowCard, ResponsiveContainer, Screen } from '@/components/ui';
import { withAdaptiveColors } from '@/hooks/adaptive-color-scope';
import { useColorTokens } from '@/hooks/use-color-tokens';
import { useThemedStyles } from '@/hooks/use-themed-styles';

import { RequestCheckBadge } from '../components/request-check-badge';
import { formatTime24 } from '../utils/move-request';
import { createStyles } from './request-sent-screen.styles';

const BACKGROUND_GRADIENT_LOCATIONS = [0, 0.5, 1] as const;

function RequestSentScreen() {
  const styles = useThemedStyles(createStyles);
  const t = useColorTokens();
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
      backgroundGradient={t.gradient.brand}
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

export default withAdaptiveColors(RequestSentScreen);
