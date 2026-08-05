import { useEffect, useState } from 'react';

import { useAuth } from '@/providers/auth-provider';
import { ApiError } from '@/services/api-error';

import { useSavedUsername } from './use-saved-username';

/** 로그인 입력값, 저장된 아이디 복원, 제출/에러 처리를 관리한다. 화면 이동은 onLoginSuccess로 주입받는다. */
export function useLoginForm(onLoginSuccess: () => void) {
  const { login } = useAuth();
  const { savedUsername, isLoaded, persistUsername, clearUsername } = useSavedUsername();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [keepSignedIn, setKeepSignedIn] = useState(true);
  const [saveUsername, setSaveUsername] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string>();

  // isLoaded 체크 없이 바로 채우면, 조회 전 기본값(빈 문자열)으로 먼저 렌더링됐다가 조회 후 다시 렌더링된다.
  useEffect(() => {
    if (!isLoaded || !savedUsername) return;
    setUsername(savedUsername);
    setSaveUsername(true);
  }, [isLoaded, savedUsername]);

  const canSubmit = username.trim().length > 0 && password.length > 0;

  const handleSubmit = async () => {
    if (!canSubmit || isSubmitting) return;

    if (saveUsername) {
      persistUsername(username.trim());
    } else {
      clearUsername();
    }

    setErrorMessage(undefined);
    setIsSubmitting(true);

    try {
      // keepSignedIn 체크를 안 하면 로그인은 되지만 기기에 세션을 저장하지 않는다.
      await login(username.trim(), password, keepSignedIn);
      onLoginSuccess();
    } catch (error) {
      if (__DEV__ || process.env.EXPO_PUBLIC_ENABLE_API_LOGS === 'true') {
        const description = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
        console.error(`[AUTH] LOGIN_FLOW_ERROR - ${description}`);
      }
      // ApiError면 서버가 준 메시지(예: "아이디 또는 비밀번호가 올바르지 않습니다")를 그대로 보여주고,
      // 네트워크 끊김처럼 서버 응답 자체가 없는 경우엔 일반적인 문구로 대체.
      setErrorMessage(error instanceof ApiError ? error.message : '로그인에 실패했습니다.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return {
    username,
    setUsername,
    password,
    setPassword,
    keepSignedIn,
    setKeepSignedIn,
    saveUsername,
    setSaveUsername,
    isSubmitting,
    errorMessage,
    canSubmit,
    handleSubmit,
  };
}
