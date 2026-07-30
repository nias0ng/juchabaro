import { Pressable, Text, View } from 'react-native';

import { styles } from './my-page-view.styles';

type MyPageMenuItem = {
  key: string;
  label: string;
  enabled: boolean;
};

// I-02(비밀번호 변경)/I-03(알림 설정)/I-04(약관 및 정책)는 이번 범위에 포함되지 않아 비활성 상태로만 노출한다.
const MENU_ITEMS: MyPageMenuItem[] = [
  { key: 'vehicles', label: '차량 관리', enabled: true },
  { key: 'password', label: '비밀번호 변경', enabled: false },
  { key: 'notification-settings', label: '알림 설정', enabled: false },
  { key: 'terms', label: '약관 및 정책', enabled: false },
];

type MyPageViewProps = {
  nickname: string;
  onNavigateToVehicles: () => void;
};

/** I-01. 내 정보. 이번 범위에서는 "차량 관리" 메뉴만 동작하고 나머지는 준비 중 표시로만 둔다. */
export function MyPageView({ nickname, onNavigateToVehicles }: MyPageViewProps) {
  const initial = nickname.trim().charAt(0) || '?';

  const handlePress = (item: MyPageMenuItem) => {
    if (item.key === 'vehicles') {
      onNavigateToVehicles();
    }
  };

  return (
    <View style={styles.container}>
      <View style={styles.profileCard}>
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>{initial}</Text>
        </View>
        <View style={styles.profileInfo}>
          <Text style={styles.profileName}>{nickname}</Text>
          <Text style={styles.profileRole}>입주민</Text>
        </View>
      </View>

      <View style={styles.menuList}>
        {MENU_ITEMS.map((item) => (
          <Pressable
            key={item.key}
            accessibilityRole="button"
            accessibilityState={{ disabled: !item.enabled }}
            disabled={!item.enabled}
            style={({ pressed }) => [
              styles.menuRow,
              !item.enabled && styles.menuRowDisabled,
              pressed && item.enabled && styles.menuRowPressed,
            ]}
            onPress={() => handlePress(item)}
          >
            <Text style={[styles.menuLabel, !item.enabled && styles.menuLabelDisabled]}>{item.label}</Text>
            {!item.enabled ? <Text style={styles.menuBadge}>준비 중</Text> : null}
          </Pressable>
        ))}
      </View>
    </View>
  );
}
