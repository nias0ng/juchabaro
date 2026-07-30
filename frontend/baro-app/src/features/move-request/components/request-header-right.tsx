import { Text, View } from 'react-native';

import { styles } from './request-header-right.styles';

type RequestSource = {
  label: string;
  variant: 'manual' | 'ai';
};

type RequestHeaderRightProps = {
  // 응답 완료(대기/상세 보기) 상태면 "저장" 링크, 응답 전이면 AUTO/MANUAL 배지를 보여준다.
  isWaiting: boolean;
  requestSource: RequestSource | null;
};

export function RequestHeaderRight({ isWaiting, requestSource }: RequestHeaderRightProps) {
  if (isWaiting) {
    return <Text style={styles.saveLink}>저장</Text>;
  }

  if (!requestSource) return null;

  const isManual = requestSource.variant === 'manual';

  return (
    <View style={[styles.badge, isManual ? styles.manualBadge : styles.aiBadge]}>
      <Text style={[styles.badgeText, isManual ? styles.manualText : styles.aiText]}>
        {requestSource.label}
      </Text>
    </View>
  );
}
