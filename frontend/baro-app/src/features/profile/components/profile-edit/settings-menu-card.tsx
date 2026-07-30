import { Pressable, Text, View } from 'react-native';

import { styles } from './settings-menu-card.styles';

type SettingsMenuCardProps = {
  onPressNotificationSettings: () => void;
};

// I-02(보기 모드)에서만 보이는 메뉴 카드. 수정 모드(I-03)로 들어가면 비밀번호/회원탈퇴가 인라인으로 바뀌며 사라진다.
export function SettingsMenuCard({ onPressNotificationSettings }: SettingsMenuCardProps) {
  return (
    <View style={styles.card}>
      <View style={[styles.row, styles.rowBorder]}>
        <Text style={styles.labelDisabled}>비밀번호 변경</Text>
        <Text style={styles.badge}>준비 중</Text>
      </View>
      <Pressable accessibilityRole="button" style={styles.row} onPress={onPressNotificationSettings}>
        <Text style={styles.label}>알림 설정</Text>
        <Text style={styles.chevron}>›</Text>
      </Pressable>
    </View>
  );
}
