import { Redirect, Tabs } from 'expo-router';
import { ActivityIndicator, View } from 'react-native';

import { TabBarIcon, TabBarLabel } from '@/components/ui';
import { useAuth } from '@/providers/auth-provider';
import { Palette } from '@/styles';

// Figma BottomTabBar(node 121:108) 기준 색상. 기존 토큰과 정확히 일치하지 않아 로컬 상수로 둔다.
const TAB_BAR_INACTIVE_COLOR = '#c8c4d7';
const TAB_BAR_BORDER_COLOR = '#e5e1ed';

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
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: Palette.violet600,
        tabBarInactiveTintColor: TAB_BAR_INACTIVE_COLOR,
        tabBarStyle: {
          backgroundColor: Palette.white,
          borderTopColor: TAB_BAR_BORDER_COLOR,
          paddingTop: 12,
        },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: '홈',
          tabBarIcon: ({ color }) => <TabBarIcon name="home" color={color} />,
          tabBarLabel: ({ focused, color }) => (
            <TabBarLabel label="홈" focused={focused} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="requests"
        options={{
          title: '요청',
          tabBarIcon: ({ color }) => <TabBarIcon name="bell" color={color} />,
          tabBarLabel: ({ focused, color }) => (
            <TabBarLabel label="요청" focused={focused} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="notifications"
        options={{
          title: '알림',
          tabBarIcon: ({ color }) => <TabBarIcon name="bell" color={color} />,
          tabBarLabel: ({ focused, color }) => (
            <TabBarLabel label="알림" focused={focused} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="my-page"
        options={{
          title: '내 정보',
          tabBarIcon: ({ color }) => <TabBarIcon name="user" color={color} />,
          tabBarLabel: ({ focused, color }) => (
            <TabBarLabel label="내 정보" focused={focused} color={color} />
          ),
        }}
      />
      {/* 탭바에는 없지만(Figma BottomTabBar 기준) 홈 화면의 "내 차량" 바로가기로는 계속 접근 가능해야 해서 라우트는 남기고 탭에서만 숨긴다. */}
      <Tabs.Screen name="vehicles" options={{ href: null }} />
    </Tabs>
  );
}
