const PLATE_NUMBER_PATTERN = /^[0-9]{2,3}\s?[가-힣]\s?[0-9]{4}$/;
const VISIT_DATE_PATTERN = /^\d{4}\.\d{2}\.\d{2}$/;

export function isPlateNumberValid(value: string) {
  return PLATE_NUMBER_PATTERN.test(value.trim());
}

export function isCarModelValid(value: string) {
  return value.trim().length > 0;
}

export function isVisitDateValid(value: string) {
  return VISIT_DATE_PATTERN.test(value);
}

/** 캘린더에서 선택한 Date를 form에 저장하는 형식(YYYY.MM.DD)으로 변환한다. */
export function toVisitDateString(date: Date) {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');

  return `${year}.${month}.${day}`;
}

/** form에 저장된 YYYY.MM.DD 문자열을 캘린더가 사용할 Date로 되돌린다. 형식이 안 맞으면 null. */
export function parseVisitDateString(value: string): Date | null {
  if (!isVisitDateValid(value)) return null;

  const [year, month, day] = value.split('.').map(Number);

  return new Date(year, month - 1, day);
}

export function isHouseholdCarFormValid(values: { plateNumber: string; carModel: string }) {
  return isPlateNumberValid(values.plateNumber) && isCarModelValid(values.carModel);
}

export function isVisitorCarFormValid(values: { plateNumber: string; visitDate: string }) {
  return isPlateNumberValid(values.plateNumber) && isVisitDateValid(values.visitDate);
}
