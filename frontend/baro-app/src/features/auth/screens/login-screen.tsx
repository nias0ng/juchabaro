import { router } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, Text } from 'react-native';

import { AppButton, ResponsiveContainer, Screen, Stack } from '@/components/ui';
import { Palette, Spacing } from '@/styles';

import { AuthHeader } from '../components/auth-header';
import { CheckboxOption } from '../components/checkbox-option';
import { TextField } from '../components/text-field';
import { styles } from './login-screen.styles';

export default function LoginScreen() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [keepSignedIn, setKeepSignedIn] = useState(true);
  const [saveUsername, setSaveUsername] = useState(false);

  const canSubmit = username.trim().length > 0 && password.length > 0;

  const handleSubmit = () => {
    if (!canSubmit) return;
    // TODO: features/auth/api 로그인 요청이 준비되면 연결한다.
  };

  return (
    <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Screen scroll backgroundColor={Palette.gray50}>
        <ResponsiveContainer>
          <Stack gap={Spacing.xl}>
            <AuthHeader title="로그인" />

            <Stack gap={Spacing.xs}>
              <Text style={styles.heading}>반가워요!</Text>
              <Text style={styles.subheading}>{'주차바로를 이용하려면\n로그인이 필요합니다'}</Text>
            </Stack>

            <Stack gap={Spacing.base}>
              <TextField
                label="아이디"
                value={username}
                onChangeText={setUsername}
                placeholder="아이디를 입력해 주세요"
                autoComplete="username"
              />
              <TextField
                label="비밀번호"
                value={password}
                onChangeText={setPassword}
                placeholder="비밀번호를 입력해 주세요"
                secureTextEntry
                autoComplete="password"
              />
            </Stack>

            <Stack direction="row" gap={Spacing.lg}>
              <CheckboxOption label="로그인 유지" checked={keepSignedIn} onChange={setKeepSignedIn} />
              <CheckboxOption label="아이디 저장" checked={saveUsername} onChange={setSaveUsername} />
            </Stack>

            <AppButton
              label="로그인"
              variant="neutral"
              size="lg"
              fullWidth
              disabled={!canSubmit}
              onPress={handleSubmit}
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
        </ResponsiveContainer>
      </Screen>
    </KeyboardAvoidingView>
  );
}
