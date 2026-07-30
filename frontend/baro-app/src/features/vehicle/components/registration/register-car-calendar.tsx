import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { styles } from './register-car-calendar.styles';

const WEEKDAY_LABELS = ['일', '월', '화', '수', '목', '금', '토'];

type RegisterCarCalendarProps = {
  /** 현재 form에 저장된 값. 있으면 초기 표시 달과 선택 표시에 사용한다. */
  selectedDate: Date | null;
  /** 날짜를 탭하면 바로 호출된다. 모달을 닫는 것은 호출부(상위)의 몫이다. */
  onSelectDate: (date: Date) => void;
};

function isSameDay(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function startOfMonth(date: Date) {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

function startOfDay(date: Date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

/**
 * 외부 패키지 없이 순수 JS Date 계산만으로 그리는 월간 그리드 캘린더.
 * 이전/다음 달 이동은 내부 상태로, 실제 선택값은 상위(form)가 소유한다.
 */
export function RegisterCarCalendar({ selectedDate, onSelectDate }: RegisterCarCalendarProps) {
  const [visibleMonth, setVisibleMonth] = useState(() => startOfMonth(selectedDate ?? new Date()));
  const today = startOfDay(new Date());

  const year = visibleMonth.getFullYear();
  const month = visibleMonth.getMonth();
  const startWeekday = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  const goToPreviousMonth = () => setVisibleMonth(new Date(year, month - 1, 1));
  const goToNextMonth = () => setVisibleMonth(new Date(year, month + 1, 1));

  const leadingBlanks = Array.from({ length: startWeekday }, (_, index) => `blank-${index}`);
  const dates = Array.from({ length: daysInMonth }, (_, index) => new Date(year, month, index + 1));

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="이전 달"
          hitSlop={8}
          style={styles.navButton}
          onPress={goToPreviousMonth}
        >
          <Text style={styles.navIcon}>{'‹'}</Text>
        </Pressable>
        <Text style={styles.headerTitle}>{`${year}년 ${month + 1}월`}</Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="다음 달"
          hitSlop={8}
          style={styles.navButton}
          onPress={goToNextMonth}
        >
          <Text style={styles.navIcon}>{'›'}</Text>
        </Pressable>
      </View>

      <View style={styles.weekdayRow}>
        {WEEKDAY_LABELS.map((label) => (
          <Text key={label} style={styles.weekdayLabel}>
            {label}
          </Text>
        ))}
      </View>

      <View style={styles.grid}>
        {leadingBlanks.map((key) => (
          <View key={key} style={styles.cell} />
        ))}
        {dates.map((date) => {
          const selected = selectedDate ? isSameDay(date, selectedDate) : false;
          const disabled = date < today;

          return (
            <Pressable
              key={date.getDate()}
              accessibilityRole="button"
              accessibilityState={{ selected, disabled }}
              disabled={disabled}
              style={styles.cell}
              onPress={() => onSelectDate(date)}
            >
              <View style={[styles.dayCircle, selected && styles.dayCircleSelected]}>
                <Text style={[styles.dayText, selected && styles.dayTextSelected, disabled && styles.dayTextDisabled]}>
                  {date.getDate()}
                </Text>
              </View>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}
