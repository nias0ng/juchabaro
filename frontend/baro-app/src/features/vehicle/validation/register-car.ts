const PLATE_NUMBER_PATTERN = /^[0-9]{2,3}[가-힣] [0-9]{4}$/;
const VISIT_DATE_PATTERN = /^\d{4}\.\d{2}\.\d{2}$/;

export function isPlateNumberValid(value: string) {
  return PLATE_NUMBER_PATTERN.test(value.trim());
}

/**
 * 입력값을 숫자 2~3자리 + 한글 1자 + 띄어쓰기 + 숫자 4자리 형식으로 강제한다.
 * 그 외 문자나 자릿수를 넘는 입력은 입력 즉시 걸러낸다.
 */
export function formatPlateNumberInput(rawInput: string): string {
  const chars = rawInput.match(/[0-9가-힣]/g) ?? [];

  let prefixDigits = '';
  let koreanChar = '';
  let suffixDigits = '';

  for (const char of chars) {
    const isDigit = char >= '0' && char <= '9';

    if (!koreanChar) {
      if (isDigit) {
        if (prefixDigits.length < 3) prefixDigits += char;
      } else {
        koreanChar = char;
      }
    } else if (isDigit && suffixDigits.length < 4) {
      suffixDigits += char;
    }
  }

  if (!koreanChar) return prefixDigits;
  if (!suffixDigits) return `${prefixDigits}${koreanChar}`;
  return `${prefixDigits}${koreanChar} ${suffixDigits}`;
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
