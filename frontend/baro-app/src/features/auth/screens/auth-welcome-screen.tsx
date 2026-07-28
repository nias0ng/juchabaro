import { BlurView } from 'expo-blur';
import { Image } from 'expo-image';
import { LinearGradient } from 'expo-linear-gradient';
import { router } from 'expo-router';
import { Text, useWindowDimensions, View } from 'react-native';

import { AppButton, ResponsiveContainer, Screen, Stack } from '@/components/ui';
import { Breakpoints, ContentWidth, Palette, Spacing } from '@/styles';

import { styles } from './auth-welcome-screen.styles';

const heroImage = require('@/assets/images/auth/welcome-hero.jpg');
const badgeIcon = require('@/assets/images/auth/welcome-badge-icon.png');

export default function AuthWelcomeScreen() {
  const { width } = useWindowDimensions();
  const isWide = width >= Breakpoints.tablet;

  return (
    <Screen scroll backgroundColor={Palette.violet50}>
      <ResponsiveContainer
        maxWidth={isWide ? ContentWidth.wide : ContentWidth.compact}
        style={styles.container}
      >
        <Stack direction="row" align="center" justify="space-between" style={styles.topNav}>
          <Text style={styles.brand}>주차바로</Text>
        </Stack>

        <View style={[styles.main, isWide && styles.mainWide]}>
          <View style={[styles.heroSection, isWide && styles.heroSectionWide]}>
            <LinearGradient
              colors={[Palette.violet100, Palette.violet50]}
              start={{ x: 0, y: 0 }}
              end={{ x: 1, y: 1 }}
              style={styles.heroGradient}
            >
              <View style={styles.heroCard}>
                <Image source={heroImage} style={styles.heroImage} contentFit="cover" />
              </View>

              <View style={styles.badge}>
                <BlurView intensity={40} tint="light" style={styles.badgeBlur}>
                  <Image source={badgeIcon} style={styles.badgeIcon} contentFit="contain" />
                  <View>
                    <Text style={styles.badgeTitle}>이동 요청됨</Text>
                    <Text style={styles.badgeSubtitle}>방금 전</Text>
                  </View>
                </BlurView>
              </View>
            </LinearGradient>
          </View>

          <View style={[styles.details, isWide && styles.detailsWide]}>
            <Stack gap={Spacing.sm} align="center" style={styles.valueProp}>
              <Text style={styles.heading}>{'주차 갈등 없이\n간편하게 이동요청'}</Text>
              <Text style={styles.subheading}>
                {'쾌적한 우리 아파트 주차 문화를\n더욱 편하게 유지하도록 돕습니다.'}
              </Text>
            </Stack>

            <Stack
              direction={isWide ? 'row' : 'column'}
              gap={Spacing.base}
              style={styles.buttonGroup}
            >
              <AppButton
                label="로그인"
                variant="neutral"
                size="lg"
                fullWidth={!isWide}
                style={isWide && styles.wideButton}
                onPress={() => router.push('/auth/login')}
              />
              <AppButton
                label="회원가입"
                variant="secondary"
                size="lg"
                fullWidth={!isWide}
                style={isWide && styles.wideButton}
                onPress={() => router.push('/auth/signup')}
              />
            </Stack>
          </View>
        </View>

        <Text style={styles.footer}>개인정보 보호 안내</Text>
      </ResponsiveContainer>
    </Screen>
  );
}
