import type { BottomTabBarProps } from '@react-navigation/bottom-tabs';
import { Redirect, Tabs } from 'expo-router';
import { ActivityIndicator, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { BottomNavBar, type NavItem } from '@/components/ui';
import { useAuth } from '@/providers/auth-provider';
import { Palette } from '@/styles';

const RESIDENT_NAV_ITEMS: NavItem[] = [
  { key: 'index', label: '홈', icon: 'home' },
  { key: 'requests', label: '요청', icon: 'request' },
  { key: 'parking-map', label: '주차 현황', icon: 'parking' },
  { key: 'my-page', label: '내 정보', icon: 'user' },
];

function ResidentBottomTabBar({ state, navigation }: BottomTabBarProps) {
  const { bottom } = useSafeAreaInsets();
  const activeKey = state.routes[state.index]?.name ?? 'index';

  const handlePressItem = (routeName: string) => {
    const route = state.routes.find((item) => item.name === routeName);
    if (!route) return;

    const event = navigation.emit({
      type: 'tabPress',
      target: route.key,
      canPreventDefault: true,
    });

    if (!event.defaultPrevented) {
      navigation.navigate(route.name, route.params);
    }
  };

  return (
    <BottomNavBar
      items={RESIDENT_NAV_ITEMS}
      activeKey={activeKey}
      bottomInset={bottom}
      onPressItem={handlePressItem}
    />
  );
}

/*
  ResidentLayout : 입주민 앱의 탭바 레이아웃
  - 홈, 요청, 주차 현황, 내 정보 탭으로 구성(Figma Z-02 개편 — 알림 탭은 빠지고 홈 화면 벨 아이콘으로만 진입)
  - 로그인하지 않은 사용자는 이 레이아웃 하위 라우트(홈/요청/주차 현황/내정보/차량 등)에 들어올 수 없다.
*/
export default function ResidentLayout() {
  const { status, user } = useAuth();

  // 세션 복원이 끝나기 전에는 guest로 단정할 수 없으므로 로딩 상태로 대기한다.
  if (status === 'loading') {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: Palette.white }}>
        <ActivityIndicator color={Palette.violet600} />
      </View>
    );
  }

  if (status === 'guest') {
    return <Redirect href="/auth/login" />;
  }

  if (user?.role !== 'RESIDENT') {
    return <Redirect href="/auth" />;
  }

  return (
    <Tabs
      tabBar={(props) => <ResidentBottomTabBar {...props} />}
      backBehavior="history"
      screenOptions={{
        headerShown: false,
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: '홈',
        }}
      />
      <Tabs.Screen
        name="requests"
        options={{
          title: '요청',
        }}
      />
      <Tabs.Screen
        name="parking-map"
        options={{
          title: '주차 현황',
        }}
      />
      <Tabs.Screen
        name="my-page"
        options={{
          title: '내 정보',
        }}
      />
      <Tabs.Screen name="vehicles" options={{ href: null }} />
      <Tabs.Screen name="notifications" options={{ href: null }} />
      <Tabs.Screen name="request-detail" options={{ href: null }} />
      <Tabs.Screen name="response-complete" options={{ href: null }} />
      <Tabs.Screen name="profile-edit" options={{ href: null }} />
      <Tabs.Screen name="notification-settings" options={{ href: null }} />
      <Tabs.Screen name="request-history" options={{ href: null }} />
      <Tabs.Screen name="violation-history" options={{ href: null }} />
    </Tabs>
  );
}
