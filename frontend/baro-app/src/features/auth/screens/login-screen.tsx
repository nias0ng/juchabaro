import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, Text } from 'react-native';

import { AppButton, ResponsiveContainer, Screen, Stack } from '@/components/ui';
import { useAuth } from '@/providers/auth-provider';
import { ApiError } from '@/services/api-error';
import { Palette, Spacing } from '@/styles';

import { AuthErrorBanner } from '../components/auth-error-banner';
import { AuthHeader } from '../components/auth-header';
import { CheckboxOption } from '../components/checkbox-option';
import { TextField } from '../components/text-field';
import { useSavedUsername } from '../hooks/use-saved-username';
import { styles } from './login-screen.styles';


export default function LoginScreen() {
  // hooks에서 가져오는 값들 -> 이전에 저장한 값들을 다시 가져오는것.
  const { login } = useAuth();
  // 저장소 접근
  const { savedUsername, isLoaded, persistUsername, clearUsername } = useSavedUsername();

  // 화면 안에서만 쓰이는 상태 값들 'useState' - 값이 바뀌면 화면이 다시 그려짐
  // username : 변수 명 & setUsername : 변수 값 바꾸는 함수
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [keepSignedIn, setKeepSignedIn] = useState(true);
  const [saveUsername, setSaveUsername] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false); //true면 로그인 요청 중이므로 버튼을 loading 상태로 바꾸고, 다시 눌러도 무시한다.
  const [errorMessage, setErrorMessage] = useState<string>();

// isLoaded 또는 savedUsername이 바뀔 때마다 실행된다.
// isLoaded 체크 없이 바로 채우면, 조회 전 기본값(null)으로 먼저 렌더링됐다가 조회 후에 다시 렌더링
useEffect(() => {
  // isLoaded: 저장소 값을 다 읽어왔는지 여부. 아직 로딩 중이거나 저장된 아이디가 없으면 아무것도 안 한다.
  if (!isLoaded || !savedUsername) return;
  setUsername(savedUsername);
  setSaveUsername(true);
}, [isLoaded, savedUsername]);

  // 로그인 버튼 활성화 여부를 결정하는 값.
  const canSubmit = username.trim().length > 0 && password.length > 0;

  // 로그인 버튼 누르면 실행되는 함수.
  const handleSubmit = async () => {

    if (!canSubmit || isSubmitting) return; // 버튼 비활성화 상태에서 눌러도 무시한다.


    // 아이디 저장
    if (saveUsername) {
      persistUsername(username.trim()); // 훅 함수
    } else {
      clearUsername();
    }

    setErrorMessage(undefined); // 이전 에러 메시지 삭제
    setIsSubmitting(true); 

    // 로그인 요청 실제 로직 -> 실패하면 error를 던지고(catch), 성공하면 router.replace()로 화면 전환
    try {

      await login(username.trim(), password, keepSignedIn); // keepSignedIn: 체크 안 하면 기기에 세션을 저장하지 않는다

      // TODO(auth-role): role(RESIDENT/ADMIN)에 따른 분기가 필요하면 여기서 처리.
      router.replace('/resident');

    } catch (error) {
      // ApiError면 서버가 준 메시지(예: "아이디 또는 비밀번호가 올바르지 않습니다")를 그대로 보여주고,
      // 네트워크 끊김처럼 서버 응답 자체가 없는 경우엔 일반적인 문구로 대체.
      setErrorMessage(error instanceof ApiError ? error.message : '로그인에 실패했습니다.');
    } finally {
      // 성공하든 실패하든 로딩 상태는 반드시 풀어줘야 한다!
      setIsSubmitting(false);
    }
  };

  // return 밑이 UI를 정의하는 영역
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
                invalid={Boolean(errorMessage)}
              />
              <TextField
                label="비밀번호"
                value={password}
                onChangeText={setPassword}
                placeholder="비밀번호를 입력해 주세요"
                secureTextEntry
                autoComplete="password"
                invalid={Boolean(errorMessage)}
              />
            </Stack>

            {errorMessage ? <AuthErrorBanner message={errorMessage} /> : null}

            <Stack direction="row" gap={Spacing.lg}>
              <CheckboxOption label="로그인 유지" checked={keepSignedIn} onChange={setKeepSignedIn} />
              <CheckboxOption label="아이디 저장" checked={saveUsername} onChange={setSaveUsername} />
            </Stack>
            <AppButton
              label={errorMessage ? '↻ 다시 로그인' : '로그인'}
              variant="neutral"
              size="lg"
              fullWidth
              disabled={!canSubmit}
              loading={isSubmitting}
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
