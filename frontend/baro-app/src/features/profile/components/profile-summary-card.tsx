import { Pressable, Text, View } from 'react-native';

import { ProfileAvatar } from './profile-avatar';
import { styles } from './profile-summary-card.styles';

type ProfileSummaryCardProps = {
  name: string;
  meta: string;
  statusLabel?: string;
  /** 지정하면 카드 전체가 눌러서 내 정보 수정으로 이동하는 버튼처럼 동작한다. */
  onPress?: () => void;
};

export function ProfileSummaryCard({ name, meta, statusLabel, onPress }: ProfileSummaryCardProps) {
  const initial = name.trim().charAt(0) || '?';

  return (
    <Pressable accessibilityRole={onPress ? 'button' : undefined} style={styles.container} onPress={onPress}>
      <ProfileAvatar label={initial} size={58} radius={22} fontSize={20} />
      <View style={styles.info}>
        <Text style={styles.name}>{name}</Text>
        <Text style={styles.meta}>{meta}</Text>
      </View>
      {statusLabel ? (
        <View style={styles.statusBadge}>
          <Text style={styles.statusText}>{statusLabel}</Text>
        </View>
      ) : null}
    </Pressable>
  );
}
