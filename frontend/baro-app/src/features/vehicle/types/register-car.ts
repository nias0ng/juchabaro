/** household/visitor는 입력 단계, confirm은 등록 정보 확인 단계다. */
export type RegisterCarStep = 'household' | 'visitor' | 'confirm';

/** confirm 단계에서도 직전에 입력하던 차량 성격을 기억해야 해서 step과 분리해 둔다. */
export type RegisterCarType = 'household' | 'visitor';

export type HouseholdCarFormValues = {
  plateNumber: string;
  carModel: string;
  isElectric: boolean;
  isDisabled: boolean;
};

export type VisitorCarFormValues = {
  plateNumber: string;
  visitDate: string;
  isElectric: boolean;
  isDisabled: boolean;
};
