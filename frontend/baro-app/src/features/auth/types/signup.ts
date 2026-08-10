/** 1~3은 입력 단계, 4는 가입 완료 안내 단계다. */
export type SignupStep = 1 | 2 | 3 | 4;

/** 완료 단계는 진행률에 포함하지 않으므로 입력 단계 수만 센다. */
export const SIGNUP_INPUT_STEP_COUNT = 3;

export type SignupAccountFormValues = {
  name: string;
  username: string;
  password: string;
  confirmPassword: string;
  phone: string;
  agreed: boolean;
};

export type SignupHouseholdFormValues = {
  buildingNumber: string;
  unitNumber: string;
  verificationConfirmed: boolean;
};

export type SignupConfirmFormValues = {
  agreeTerms: boolean;
  agreePrivacy: boolean;
};
