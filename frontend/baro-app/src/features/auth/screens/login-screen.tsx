import { router } from 'expo-router';
import { Pressable, Text } from 'react-native';

import {
  AppButton,
  CheckboxOption,
  FormErrorBanner,
  ResponsiveContainer,
  Screen,
  ScreenHeader,
  Stack,
  TextField,
} from '@/components/ui';
import { Palette, Spacing } from '@/styles';

import { useLoginForm } from '../hooks/use-login-form';
import { styles } from './login-screen.styles';

export default function LoginScreen() {
  // TODO(auth-role): role(RESIDENT/ADMIN)에 따른 분기가 필요하면 여기서 처리.
  const form = useLoginForm(() => router.replace('/resident'));

  return (
    <Screen scroll avoidKeyboard backgroundColor={Palette.gray50}>
      <ResponsiveContainer>
        <Stack>
          <ScreenHeader title="로그인" />

          <Stack gap={Spacing.xl}>
            <Stack gap={Spacing.xs}>
              <Text style={styles.heading}>반가워요!</Text>
              <Text style={styles.subheading}>{'주차바로를 이용하려면\n로그인이 필요합니다'}</Text>
            </Stack>

            <Stack gap={Spacing.base}>
              <TextField
                label="아이디"
                value={form.username}
                onChangeText={form.setUsername}
                placeholder="아이디를 입력해 주세요"
                autoComplete="username"
                invalid={Boolean(form.errorMessage)}
              />
              <TextField
                label="비밀번호"
                value={form.password}
                onChangeText={form.setPassword}
                placeholder="비밀번호를 입력해 주세요"
                secureTextEntry
                autoComplete="password"
                invalid={Boolean(form.errorMessage)}
              />
            </Stack>

            {form.errorMessage ? <FormErrorBanner message={form.errorMessage} /> : null}

            <Stack direction="row" gap={Spacing.lg}>
              <CheckboxOption label="로그인 유지" checked={form.keepSignedIn} onChange={form.setKeepSignedIn} />
              <CheckboxOption label="아이디 저장" checked={form.saveUsername} onChange={form.setSaveUsername} />
            </Stack>
            <AppButton
              label={form.errorMessage ? '↻ 다시 로그인' : '로그인'}
              variant="neutral"
              size="lg"
              fullWidth
              disabled={!form.canSubmit}
              loading={form.isSubmitting}
              onPress={form.handleSubmit}
            />

            <Pressable
              accessibilityRole="button"
              style={styles.footerRow}
              onPress={() => router.push('/auth/signup')}
            >
              <Text style={styles.footerText}>
                아직 계정이 없으신가요? <Text style={styles.footerLink}>회원가입</Text>
              </Text>
            </Pressable>
          </Stack>
        </Stack>
      </ResponsiveContainer>
    </Screen>
  );
}
