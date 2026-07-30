import { Image } from 'expo-image';
import { LinearGradient } from 'expo-linear-gradient';
import { router } from 'expo-router';
import { Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppButton, Stack } from '@/components/ui';
import { Gradients, Spacing } from '@/styles';

import { styles } from './auth-welcome-screen.styles';

const logo = require('@/assets/images/auth/welcome-logo.png');

export default function AuthWelcomeScreen() {
  return (
    <LinearGradient
      colors={Gradients.authWelcome}
      start={{ x: 0, y: 0 }}
      end={{ x: 1, y: 1 }}
      style={styles.gradient}
    >
      <SafeAreaView style={styles.safeArea}>
        <View style={styles.content}>
          <Stack gap={Spacing.md}>
            <View style={styles.logoBadge}>
              <Image source={logo} style={styles.logo} contentFit="contain" />
            </View>

            <Stack gap={Spacing.xxs} align="center">
              <Text style={styles.brand}>주차바로</Text>
              <Text style={styles.tagline}>주차 갈등, 바로에게 맡기세요.</Text>
            </Stack>

            <Stack gap={Spacing.base} style={styles.buttonGroup}>
              <AppButton
                label="로그인"
                variant="neutral"
                size="lg"
                fullWidth
                onPress={() => router.push('/auth/login')}
              />
              <AppButton
                label="회원가입"
                variant="secondary"
                size="lg"
                fullWidth
                onPress={() => router.push('/auth/signup')}
              />
            </Stack>
          </Stack>
        </View>

        <Text style={styles.footer}>SSAFY Carsavo Technology 제공</Text>
      </SafeAreaView>
    </LinearGradient>
  );
}
