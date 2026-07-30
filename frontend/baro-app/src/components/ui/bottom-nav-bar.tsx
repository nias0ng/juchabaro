import { Pressable, Text, View } from 'react-native';

import { useTheme } from '@/hooks/use-theme';

import { REQUEST_ICON_PATH, REQUEST_ICON_VIEWBOX_SIZE, STROKE_ICON_PATHS } from './bottom-nav-bar-icons';
import { IconGlyph } from './icon-glyph';
import { styles } from './bottom-nav-bar.styles';

type NavIconKey = 'home' | 'request' | 'bell' | 'user';

export type NavItem = {
  key: string;
  label: string;
  icon: NavIconKey;
  badge?: boolean;
};

// Figma 기본 4탭(홈/요청/알림/내정보) 프리셋.
export const DEFAULT_NAV_ITEMS: NavItem[] = [
  { key: 'home', label: '홈', icon: 'home' },
  { key: 'request', label: '요청', icon: 'request' },
  { key: 'bell', label: '알림', icon: 'bell' },
  { key: 'user', label: '내정보', icon: 'user' },
];

// Figma 실측값(비활성 아이콘/라벨 색상, 상단 구분선 색상) — 현재 테마 토큰과 정확히 일치하지 않는다.
const INACTIVE_COLOR = '#9ca3af';
const BORDER_COLOR = '#f3f4f6';

type BottomNavBarProps = {
  items?: NavItem[];
  activeKey: string;
  onPressItem: (key: string) => void;
};

/** Figma Z-02. BottomNavBar를 그대로 재현한 프레젠테이션 컴포넌트. 어떤 네비게이터에도 연결되어 있지 않다. */
export function BottomNavBar({ items = DEFAULT_NAV_ITEMS, activeKey, onPressItem }: BottomNavBarProps) {
  const theme = useTheme();

  return (
    <View style={[styles.container, { borderTopColor: BORDER_COLOR, backgroundColor: theme.surface }]}>
      {items.map((item) => {
        const focused = item.key === activeKey;
        const color = focused ? theme.primary : INACTIVE_COLOR;

        return (
          <Pressable
            key={item.key}
            accessibilityRole="button"
            accessibilityLabel={item.label}
            accessibilityState={{ selected: focused }}
            onPress={() => onPressItem(item.key)}
            style={styles.tab}
          >
            <View style={styles.iconContainer}>
              {item.icon === 'request' ? (
                <IconGlyph
                  d={REQUEST_ICON_PATH}
                  color={color}
                  variant="fill"
                  viewBoxSize={REQUEST_ICON_VIEWBOX_SIZE}
                />
              ) : (
                <IconGlyph d={STROKE_ICON_PATHS[item.icon]} color={color} />
              )}
              {item.badge ? <View style={styles.badge} /> : null}
            </View>
            <Text style={[styles.label, { color }]}>{item.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}
