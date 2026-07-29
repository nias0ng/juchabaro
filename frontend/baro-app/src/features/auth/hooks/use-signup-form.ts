import { useCallback, useMemo, useState } from 'react';

import { ApiError } from '@/services/api-error';

import { signup } from '../api/auth-api';
import type {
  SignupAccountFormValues,
  SignupConfirmFormValues,
  SignupHouseholdFormValues,
  SignupStep,
} from '../types/signup';
import { isAccountFormValid, isConfirmFormValid, isHouseholdFormValid } from '../validation/signup';

const INITIAL_ACCOUNT_VALUES: SignupAccountFormValues = {
  name: '',
  username: '',
  password: '',
  confirmPassword: '',
  phone: '',
  agreed: false,
};

const INITIAL_HOUSEHOLD_VALUES: SignupHouseholdFormValues = {
  buildingNumber: '',
  unitNumber: '',
  verificationConfirmed: false,
};

const INITIAL_CONFIRM_VALUES: SignupConfirmFormValues = {
  agreeTerms: false,
  agreePrivacy: false,
};

// TODO(#291): 단지 정보 API가 준비되면 로그인 초대 코드 또는 설정값에서 가져온다.
const COMPLEX_NAME = 'SSAFY 아파트';

/**
 * 회원가입 3단계 입력값과 단계 이동을 함께 관리한다.
 * 화면은 프레임만 담당하고 단계별 상태 판단은 이 훅에서 끝낸다.
 */
export function useSignupForm() {
  const [step, setStep] = useState<SignupStep>(1);
  const [accountValues, setAccountValues] = useState(INITIAL_ACCOUNT_VALUES);
  const [householdValues, setHouseholdValues] = useState(INITIAL_HOUSEHOLD_VALUES);
  const [confirmValues, setConfirmValues] = useState(INITIAL_CONFIRM_VALUES);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string>();

  const canSubmitStep = useMemo(() => {
    if (step === 1) return isAccountFormValid(accountValues);
    if (step === 2) return isHouseholdFormValid(householdValues);
    if (step === 3) return isConfirmFormValid(confirmValues);
    return true;
  }, [step, accountValues, householdValues, confirmValues]);

  const changeAccountValue = useCallback(
    <K extends keyof SignupAccountFormValues>(key: K, value: SignupAccountFormValues[K]) => {
      setAccountValues((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const changeHouseholdValue = useCallback(
    <K extends keyof SignupHouseholdFormValues>(key: K, value: SignupHouseholdFormValues[K]) => {
      setHouseholdValues((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const changeConfirmValue = useCallback(
    <K extends keyof SignupConfirmFormValues>(key: K, value: SignupConfirmFormValues[K]) => {
      setConfirmValues((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const goToStep = useCallback((target: SignupStep) => {
    setErrorMessage(undefined);
    setStep(target);
  }, []);

  // 첫 단계에서는 이전 단계가 없어 헤더의 뒤로 가기가 기본 동작을 사용하도록 비워 둔다.
  const goToPreviousStep =
    step === 1 ? undefined : () => goToStep((step - 1) as SignupStep);

  const goToNextStep = async () => {
    if (!canSubmitStep || isSubmitting) return;

    if (step === 3) {
      setErrorMessage(undefined);
      setIsSubmitting(true);

      try {
        await signup({
          loginId: accountValues.username,
          password: accountValues.password,
          phoneNumber: accountValues.phone,
          name: accountValues.name,
          buildingNumber: householdValues.buildingNumber,
          unitNumber: householdValues.unitNumber,
        });
        setStep(4);
      } catch (error) {
        // ApiError면 서버 메시지(예: "이미 사용 중인 로그인 아이디입니다")를 그대로 보여준다.
        setErrorMessage(error instanceof ApiError ? error.message : '회원가입에 실패했습니다.');
      } finally {
        setIsSubmitting(false);
      }
      return;
    }

    if (step === 1 || step === 2) {
      goToStep((step + 1) as SignupStep);
    }
  };

  return {
    step,
    complexName: COMPLEX_NAME,
    accountValues,
    householdValues,
    confirmValues,
    isSubmitting,
    errorMessage,
    canSubmitStep,
    changeAccountValue,
    changeHouseholdValue,
    changeConfirmValue,
    goToStep,
    goToPreviousStep,
    goToNextStep,
  };
}

export type SignupFormController = ReturnType<typeof useSignupForm>;
