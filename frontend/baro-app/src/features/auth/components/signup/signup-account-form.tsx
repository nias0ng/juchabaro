import { Stack } from '@/components/ui';
import { Spacing } from '@/styles';

import type { SignupAccountFormValues } from '../../types/signup';
import {
  PHONE_MAX_LENGTH,
  formatPhoneNumber,
  isConfirmPasswordValid,
  isPasswordValid,
  isPhoneValid,
  isUsernameValid,
} from '../../validation/signup';

import { CheckboxOption } from '../checkbox-option';
import { SignupStepHeading } from './signup-step-heading';
import { TextField } from '../text-field';

type SignupAccountFormProps = {
  values: SignupAccountFormValues;
  onChange: <K extends keyof SignupAccountFormValues>(
    key: K,
    value: SignupAccountFormValues[K],
  ) => void;
};

export function SignupAccountForm({ values, onChange }: SignupAccountFormProps) {
  const usernameValid = isUsernameValid(values.username);
  const passwordValid = isPasswordValid(values.password);
  const phoneValid = isPhoneValid(values.phone);
  const confirmPasswordValid = isConfirmPasswordValid(values.password, values.confirmPassword);

  return (
    <Stack gap={Spacing.xl}>
      <SignupStepHeading
        title={'사용하실 계정을\n만들어 주세요'}
        description="정확한 정보를 입력해야 서비스 이용이 가능해요"
      />

      <Stack gap={Spacing.base}>
        <TextField
          label="이름"
          value={values.name}
          onChangeText={(text) => onChange('name', text)}
          placeholder="이름을 입력해 주세요"
        />

        {/* TODO(#291): 아이디 중복 확인 API가 연동되면 features/auth/api + 훅으로 분리해 붙인다. */}
        <TextField
          label="아이디"
          value={values.username}
          onChangeText={(text) => onChange('username', text)}
          placeholder="영문, 숫자 4~20자"
          autoComplete="username"
          error={
            values.username.length > 0 && !usernameValid
              ? '영문, 숫자 4~20자로 입력해 주세요'
              : undefined
          }
        />

        <TextField
          label="비밀번호"
          value={values.password}
          onChangeText={(text) => onChange('password', text)}
          placeholder="비밀번호를 입력해 주세요"
          secureTextEntry
          autoComplete="password-new"
          helperText="최소 8자 · 영문 · 숫자 · 특수문자를 포함해 주세요"
          error={
            values.password.length > 0 && !passwordValid
              ? '영문, 숫자, 특수문자를 모두 포함해 8자 이상 입력해 주세요'
              : undefined
          }
        />

        <TextField
          label="비밀번호 확인"
          value={values.confirmPassword}
          onChangeText={(text) => onChange('confirmPassword', text)}
          placeholder="비밀번호를 다시 입력해 주세요"
          secureTextEntry
          autoComplete="password-new"
          error={
            values.confirmPassword.length > 0 && !confirmPasswordValid
              ? '비밀번호가 일치하지 않아요'
              : undefined
          }
        />

        <TextField
          label="전화번호"
          value={values.phone}
          onChangeText={(text) => onChange('phone', formatPhoneNumber(text))}
          placeholder="010-1234-5678"
          keyboardType="number-pad"
          maxLength={PHONE_MAX_LENGTH}
          helperText="숫자만 입력하면 하이픈이 자동으로 채워져요"
          error={
            values.phone.length > 0 && !phoneValid ? '010-1234-5678 형식으로 입력해 주세요' : undefined
          }
        />
      </Stack>

      <CheckboxOption
        label="이용약관 및 개인정보 처리방침에 동의합니다"
        checked={values.agreed}
        onChange={(checked) => onChange('agreed', checked)}
      />
    </Stack>
  );
}
