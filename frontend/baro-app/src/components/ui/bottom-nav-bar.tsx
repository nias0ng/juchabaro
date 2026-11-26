import { Pressable, Text, View } from 'react-native';

import { withAdaptiveColors } from '@/hooks/adaptive-color-scope';
import { useColorTokens } from '@/hooks/use-color-tokens';
import { useThemedStyles } from '@/hooks/use-themed-styles';

import {
  PARKING_ICON_PATHS,
  PARKING_ICON_VIEWBOX_SIZE,
  REQUEST_ICON_PATH,
  REQUEST_ICON_VIEWBOX_SIZE,
  STROKE_ICON_PATHS,
} from './bottom-nav-bar-icons';
import { IconGlyph } from './icon-glyph';
import { createStyles } from './bottom-nav-bar.styles';

type NavIconKey = 'home' | 'request' | 'parking' | 'user';

export type NavItem = {
  key: string;
  label: string;
  icon: NavIconKey;
  badge?: boolean;
};

// Figma 기본 4탭(홈/요청/주차 현황/내정보) 프리셋.
export const DEFAULT_NAV_ITEMS: NavItem[] = [
  { key: 'home', label: '홈', icon: 'home' },
  { key: 'request', label: '요청', icon: 'request' },
  { key: 'parking', label: '주차 현황', icon: 'parking' },
  { key: 'user', label: '내 정보', icon: 'user' },
];

type BottomNavBarProps = {
  items?: NavItem[];
  activeKey: string;
  onPressItem: (key: string) => void;
  bottomInset?: number;
};

function BottomNavBarView({
  items = DEFAULT_NAV_ITEMS,
  activeKey,
  onPressItem,
  bottomInset = 0,
}: BottomNavBarProps) {
  const t = useColorTokens();
  const styles = useThemedStyles(createStyles);

  return (
    <View
      style={[
        styles.container,
        {
          borderTopColor: t.stroke.weak,
          backgroundColor: t.background.raised,
          paddingBottom: Math.max(styles.container.paddingBottom, bottomInset),
        },
      ]}
    >
      <View style={styles.tabsRow}>
        {items.map((item) => {
          const focused = item.key === activeKey;
          // 라벨은 본문 글자 기준(4.5), 아이콘은 아이콘 기준(3)을 따르므로 비활성 색을 따로 둔다.
          const iconColor = focused ? t.text.brand : t.icon.weak;
          const labelColor = focused ? t.text.brand : t.text.weaker;

          return (
            <Pressable
              key={item.key}
              accessibilityRole="button"
              accessibilityLabel={item.label}
              accessibilityState={{ selected: focused }}
              onPress={() => onPressItem(item.key)}
              style={[styles.tab, item.icon === 'home' && styles.homeTab]}
            >
              <View style={styles.iconContainer}>
                {item.icon === 'request' ? (
                  <IconGlyph
                    d={REQUEST_ICON_PATH}
                    color={iconColor}
                    variant="fill"
                    viewBoxSize={REQUEST_ICON_VIEWBOX_SIZE}
                    fillOutlineWidth={0.6}
                  />
                ) : item.icon === 'parking' ? (
                  <IconGlyph
                    d={PARKING_ICON_PATHS}
                    color={iconColor}
                    variant="fill"
                    size={24}
                    viewBoxSize={PARKING_ICON_VIEWBOX_SIZE}
                  />
                ) : (
                  <IconGlyph
                    d={STROKE_ICON_PATHS[item.icon]}
                    color={iconColor}
                    size={item.icon === 'home' ? 23 : undefined}
                  />
                )}
                {item.badge ? <View style={styles.badge} /> : null}
              </View>
              <Text style={[styles.label, { color: labelColor }]}>{item.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

/**
 * Figma Z-02. 네비게이터와 분리된 하단 탭 UI. activeKey와 onPressItem으로 실제 라우팅에 연결한다.
 * 자기 배경을 스스로 칠하는 독립된 면이라, 화면이 옮겨졌는지와 상관없이 기기의 라이트/다크 모드를 따른다.
 */
export const BottomNavBar = withAdaptiveColors(BottomNavBarView);
