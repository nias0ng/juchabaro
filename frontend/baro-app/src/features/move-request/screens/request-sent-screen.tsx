import { LinearGradient } from 'expo-linear-gradient';
import { router } from 'expo-router';
import { Pressable, Text, View } from 'react-native';

import { InfoRowCard, Screen } from '@/components/ui';
import { Gradients } from '@/styles';

import { styles } from './request-sent-screen.styles';

const BACKGROUND_GRADIENT = ['#eae7fb', '#f7f6fb'] as const;
const BACKGROUND_GRADIENT_LOCATIONS = [0, 0.5] as const;

// TODO(request-sent): E-02(이동 요청 작성) 화면이 아직 없어서, 그 화면이 만들어지면
// 실제로 전송한 요청 정보(requestId 등)를 파라미터로 받아 표시하도록 바꿔야 한다.
const MOCK_REQUEST = {
  plateNumber: '12가 ****',
  situationLabel: '이중 주차 · 긴급',
  requestedAtLabel: '15:00',
};

export default function RequestSentScreen() {
  return (
    <Screen
      edges={['top', 'right', 'left']}
      backgroundGradient={BACKGROUND_GRADIENT}
      backgroundGradientLocations={BACKGROUND_GRADIENT_LOCATIONS}
      contentContainerStyle={styles.content}
    >
      <View style={styles.iconOuter}>
        <LinearGradient colors={Gradients.avatar} style={styles.iconInner} />
      </View>

      <Text style={styles.title}>{'이동 요청을\n전송했습니다'}</Text>
      <Text style={styles.subtitle}>
        {'차주에게 알림이 전달되었습니다.\n응답이 오면 바로 알려드리겠습니다.'}
      </Text>

      <View style={styles.summaryMargin}>
        <InfoRowCard
          rows={[
            { label: '대상 차량', value: MOCK_REQUEST.plateNumber },
            { label: '상황', value: MOCK_REQUEST.situationLabel },
            { label: '요청 시각', value: MOCK_REQUEST.requestedAtLabel },
          ]}
        />
      </View>

      <View style={styles.noticeBox}>
        <Text style={styles.noticeText}>
          {'10분 내 응답이 없으면 자동으로 1회 재알림이 발송되며, 그 후에도\n응답이 없으면 관리사무소로 전달됩니다.'}
        </Text>
      </View>

      <View style={styles.actions}>
        {/* TODO(request-sent): 이 요청의 requestId를 받으면 request-detail로 이동하도록 연결한다. */}
        <Pressable accessibilityRole="button" style={styles.primaryButton}>
          <Text style={styles.primaryButtonText}>요청 상태 보기</Text>
        </Pressable>

        <Pressable accessibilityRole="button" style={styles.secondaryButton} onPress={() => router.replace('/resident')}>
          <Text style={styles.secondaryButtonText}>홈으로</Text>
        </Pressable>
      </View>
    </Screen>
  );
}
