import type {
  SignupAccountFormValues,
  SignupConfirmFormValues,
  SignupHouseholdFormValues,
} from '../types/signup';

const USERNAME_PATTERN = /^[a-zA-Z0-9_]{4,20}$/;
const PASSWORD_PATTERN = /^(?=.*[A-Za-z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,}$/;
const UNIT_NUMBER_PATTERN = /^\d{1,4}$/;

/**
 * 전화번호는 `010-1234-5678` 한 가지 형식만 허용한다.
 * 숫자만 입력해도 formatPhoneNumber가 하이픈을 채우므로 저장되는 값의 형식은 항상 같다.
 * 국내 휴대전화 번호는 모두 11자리라서 가운데 자리는 4자리로 고정한다.
 */
const PHONE_PATTERN = /^01[016789]-\d{4}-\d{4}$/;
const PHONE_DIGIT_COUNT = 11;

/** 숫자 11자리 + 하이픈 2개 */
export const PHONE_MAX_LENGTH = PHONE_DIGIT_COUNT + 2;

export function isUsernameValid(username: string) {
  return USERNAME_PATTERN.test(username);
}

export function isPasswordValid(password: string) {
  return PASSWORD_PATTERN.test(password);
}

export function isConfirmPasswordValid(password: string, confirmPassword: string) {
  return confirmPassword.length > 0 && confirmPassword === password;
}

export function isPhoneValid(phone: string) {
  return PHONE_PATTERN.test(phone);
}

export function isUnitNumberValid(value: string) {
  return UNIT_NUMBER_PATTERN.test(value);
}

/** 입력 중에도 형식이 흔들리지 않도록 숫자만 남긴 뒤 3-4-4로 다시 끊는다. */
export function formatPhoneNumber(input: string) {
  const digits = input.replace(/\D/g, '').slice(0, PHONE_DIGIT_COUNT);

  if (digits.length <= 3) {
    return digits;
  }

  if (digits.length <= 7) {
    return `${digits.slice(0, 3)}-${digits.slice(3)}`;
  }

  return `${digits.slice(0, 3)}-${digits.slice(3, 7)}-${digits.slice(7)}`;
}

export function isAccountFormValid(values: SignupAccountFormValues) {
  return (
    values.name.trim().length > 0 &&
    isUsernameValid(values.username) &&
    isPasswordValid(values.password) &&
    isConfirmPasswordValid(values.password, values.confirmPassword) &&
    isPhoneValid(values.phone) &&
    values.agreed
  );
}

export function isHouseholdFormValid(values: SignupHouseholdFormValues) {
  return (
    isUnitNumberValid(values.buildingNumber) &&
    isUnitNumberValid(values.unitNumber) &&
    values.verificationConfirmed
  );
}

export function isConfirmFormValid(values: SignupConfirmFormValues) {
  return values.agreeTerms && values.agreePrivacy;
}
