import { Text, View } from 'react-native';

import { styles } from './quiet-hours-card.styles';

type QuietHoursCardProps = {
  startLabel: string;
  endLabel: string;
};

// 방해 금지 시간. 백엔드 저장 API도 없고 프로젝트에 시간 선택 UI도 아직 없어 값은 고정 표시만 한다.
export function QuietHoursCard({ startLabel, endLabel }: QuietHoursCardProps) {
  return (
    <View style={styles.card}>
      <Text style={styles.title}>방해 금지 시간</Text>

      <View style={styles.timeRow}>
        <View style={styles.timeBox}>
          <Text style={styles.timeLabel}>시작</Text>
          <Text style={styles.timeValue}>{startLabel}</Text>
        </View>
        <View style={styles.timeBox}>
          <Text style={styles.timeLabel}>종료</Text>
          <Text style={styles.timeValue}>{endLabel}</Text>
        </View>
      </View>

      <View style={styles.notice}>
        <Text style={styles.noticeText}>긴급 이동 요청은 방해 금지 시간에도 발송됩니다.</Text>
      </View>
    </View>
  );
}
