import { Tabs } from 'expo-router';

export default function ResidentLayout() {
  return (
    <Tabs screenOptions={{ headerShown: false }}>
      <Tabs.Screen name="index" options={{ title: '홈' }} />
      <Tabs.Screen name="notifications" options={{ title: '알림' }} />
      <Tabs.Screen name="vehicles" options={{ title: '차량' }} />
      <Tabs.Screen name="my-page" options={{ title: '마이' }} />
    </Tabs>
  );
}
