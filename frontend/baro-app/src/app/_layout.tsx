import { DarkTheme, DefaultTheme, ThemeProvider } from '@react-navigation/native';
import { Stack } from 'expo-router';
import { useColorScheme } from 'react-native';

import { PushTokenRegistrar } from '@/features/notification/components/push-token-registrar';
import { AuthProvider } from '@/providers/auth-provider';

import '@/styles/global.css';

export default function RootLayout() {
  const colorScheme = useColorScheme();

  return (
    <ThemeProvider value={colorScheme === 'dark' ? DarkTheme : DefaultTheme}>
      <AuthProvider>
        <PushTokenRegistrar />
        <Stack screenOptions={{ headerShown: false }}>
          <Stack.Screen name="index" />
          <Stack.Screen name="auth" />
          <Stack.Screen name="resident" />
        </Stack>
      </AuthProvider>
    </ThemeProvider>
  );
}
