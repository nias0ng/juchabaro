const PLATE_NUMBER_PATTERN = /^[0-9]{2,3}[가-힣] [0-9]{4}$/;
const VISIT_DATE_PATTERN = /^\d{4}\.\d{2}\.\d{2}$/;

export function isPlateNumberValid(value: string) {
  return PLATE_NUMBER_PATTERN.test(value.trim());
}

/**
 * 입력값을 숫자 2~3자리 + 한글 1자 + 띄어쓰기 + 숫자 4자리 형식으로 강제한다.
 * 그 외 문자나 자릿수를 넘는 입력은 입력 즉시 걸러낸다.
 *
 * 한글은 자모(ㄱ, ㅏ 등: U+3131~U+318E)가 조합되는 도중에도 한 글자로 쳐준다 — 완성된 음절(가~힣)만
 * 허용하면, 조합 중인 자모가 이 함수에서 걸러져서 controlled value가 IME 조합 상태보다 짧아지고,
 * 그 순간 브라우저가 조합을 리셋하면서 직전에 입력된 숫자까지 같이 날아가 버린다.
 */
export function formatPlateNumberInput(rawInput: string): string {
  const chars = rawInput.match(/[0-9가-힣ㄱ-ㅎㅏ-ㅣ]/g) ?? [];

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
    } else if (!isDigit) {
      // 조합 중인 자모가 다른 자모로 계속 바뀌는 동안(예: ㄱ → 가) 완성될 때까지 갱신해준다.
      koreanChar = char;
    }
  }

  if (!koreanChar) return prefixDigits;
  if (!suffixDigits) return `${prefixDigits}${koreanChar}`;
  return `${prefixDigits}${koreanChar} ${suffixDigits}`;
}

/** 입력 필드는 "12가 3456"처럼 띄어쓰기로 보여주지만, API는 공백 없는 "12가3456"을 요구한다. */
export function toApiPlateNumber(plateNumber: string): string {
  return plateNumber.replace(' ', '');
}

const PLATE_NUMBER_DISPLAY_PATTERN = /^([0-9]{2,3}[가-힣])([0-9]{4})$/;

export function formatPlateNumberDisplay(plateNumber: string): string {
  const match = plateNumber.match(PLATE_NUMBER_DISPLAY_PATTERN);
  return match ? `${match[1]} ${match[2]}` : plateNumber;
}

/** 폼에 저장된 "YYYY.MM.DD"를 API가 요구하는 "YYYY-MM-DD"로 변환한다. */
export function toApiVisitDate(visitDate: string): string {
  return visitDate.replaceAll('.', '-');
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
