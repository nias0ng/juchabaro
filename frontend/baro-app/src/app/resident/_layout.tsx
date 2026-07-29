import { Tabs } from 'expo-router';

import { FontWeight, Palette } from '@/styles';

/*
  ResidentLayout : 입주민 앱의 탭바 레이아웃
  - 홈, 요청, 알림, 내 정보 탭으로 구성
*/
export default function ResidentLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: Palette.violet600,
        tabBarInactiveTintColor: Palette.gray300,
        tabBarStyle: {
          backgroundColor: Palette.white,
          borderTopColor: Palette.gray200,
        },
        tabBarLabelStyle: {
          fontSize: 12,
          fontWeight: FontWeight.medium,
        },
        tabBarItemStyle: {
          paddingVertical: 12,
        },
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
    </Tabs>
  );
}
