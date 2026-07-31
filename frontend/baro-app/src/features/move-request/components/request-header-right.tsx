import { Text, View } from 'react-native';

import { styles } from './request-header-right.styles';

type RequestSource = {
  label: string;
  variant: 'manual' | 'ai';
};

type RequestHeaderRightProps = {
  requestSource: RequestSource | null;
};

export function RequestHeaderRight({ requestSource }: RequestHeaderRightProps) {
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
