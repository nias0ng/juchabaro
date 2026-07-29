const PLATE_NUMBER_PATTERN = /^[0-9]{2,3}\s?[가-힣]\s?[0-9]{4}$/;
const VISIT_DATE_PATTERN = /^\d{4}\.\d{2}\.\d{2}$/;
const VISIT_DATE_DIGIT_COUNT = 8;

/** 숫자 8자리 + 마침표 2개 */
export const VISIT_DATE_MAX_LENGTH = VISIT_DATE_DIGIT_COUNT + 2;

export function isPlateNumberValid(value: string) {
  return PLATE_NUMBER_PATTERN.test(value.trim());
}

export function isCarModelValid(value: string) {
  return value.trim().length > 0;
}

export function isVisitDateValid(value: string) {
  return VISIT_DATE_PATTERN.test(value);
}

/** 입력 중에도 형식이 흔들리지 않도록 숫자만 남긴 뒤 4-2-2(YYYY.MM.DD)로 다시 끊는다. */
export function formatVisitDate(input: string) {
  const digits = input.replace(/\D/g, '').slice(0, VISIT_DATE_DIGIT_COUNT);

  if (digits.length <= 4) {
    return digits;
  }

  if (digits.length <= 6) {
    return `${digits.slice(0, 4)}.${digits.slice(4)}`;
  }

  return `${digits.slice(0, 4)}.${digits.slice(4, 6)}.${digits.slice(6)}`;
}

export function isHouseholdCarFormValid(values: { plateNumber: string; carModel: string }) {
  return isPlateNumberValid(values.plateNumber) && isCarModelValid(values.carModel);
}

export function isVisitorCarFormValid(values: { plateNumber: string; visitDate: string }) {
  return isPlateNumberValid(values.plateNumber) && isVisitDateValid(values.visitDate);
}
