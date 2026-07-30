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
  { key: 'notifications', label: '알림', icon: 'bell' },
  { key: 'my-page', label: '내정보', icon: 'user' },
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
  - 홈, 요청, 알림, 내 정보 탭으로 구성
  - 로그인하지 않은 사용자는 이 레이아웃 하위 라우트(홈/요청/알림/내정보/차량 등)에 들어올 수 없다.
*/
export default function ResidentLayout() {
  const { status } = useAuth();

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

  return (
    <Tabs
      tabBar={(props) => <ResidentBottomTabBar {...props} />}
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
        name="notifications"
        options={{
          title: '알림',
        }}
      />
      <Tabs.Screen
        name="my-page"
        options={{
          title: '내 정보',
        }}
      />
      {/* 탭바에는 없지만(Figma BottomTabBar 기준) 홈 화면의 "내 차량" 바로가기로는 계속 접근 가능해야 해서 라우트는 남기고 탭에서만 숨긴다. */}
      <Tabs.Screen name="vehicles" options={{ href: null }} />
      {/* 이동 요청 상세는 URL/알림에서 접근하지만 하단 탭 항목으로는 노출하지 않는다. */}
      <Tabs.Screen name="request-detail" options={{ href: null }} />
      {/* F-02 응답 완료는 E-11에서 응답 후 도달하는 화면이라 하단 탭 항목으로는 노출하지 않는다. */}
      <Tabs.Screen name="response-complete" options={{ href: null }} />
      {/* I-02/I-03 내 정보 수정은 내 정보 카드를 눌러서 진입하는 화면이라 하단 탭 항목으로는 노출하지 않는다. */}
      <Tabs.Screen name="profile-edit" options={{ href: null }} />
      {/* I-04 알림 설정은 내 정보 화면의 메뉴로 진입하는 화면이라 하단 탭 항목으로는 노출하지 않는다. */}
      <Tabs.Screen name="notification-settings" options={{ href: null }} />
      {/* 요청 내역도 내 정보 화면의 메뉴로 진입하는 화면이라 하단 탭 항목으로는 노출하지 않는다. */}
      <Tabs.Screen name="request-history" options={{ href: null }} />
    </Tabs>
  );
}
