import { Text, View } from 'react-native';

import { useThemedStyles } from '@/hooks/use-themed-styles';

import { createStyles } from './info-row-card.styles';

export type InfoRow = {
  label: string;
  value: string;
};

export type InfoRowCardStatusRow = {
  label: string;
  time: string;
  dotColor?: string;
};

type InfoRowCardProps = {
  rows: InfoRow[];
  /** 있으면 구분선 아래에 상태 점 + 라벨 + 시각을 한 줄 더 보여준다(예: "요청자에게 전달 완료"). */
  statusRow?: InfoRowCardStatusRow;
};

/**
 * 흰 카드에 "라벨 ↔ 값" 행을 나열하는 요약 카드. F-02(응답 완료), E-03(요청 전송 완료)처럼
 * 완료/확인 화면에서 반복되는 패턴이라 공용 컴포넌트로 둔다.
 */
export function InfoRowCard({ rows, statusRow }: InfoRowCardProps) {
  const styles = useThemedStyles(createStyles);

  return (
    <View style={styles.container}>
      {rows.map((row) => (
        <View key={row.label} style={styles.row}>
          <Text style={styles.label}>{row.label}</Text>
          <Text style={styles.value}>{row.value}</Text>
        </View>
      ))}

      {statusRow ? (
        <>
          <View style={styles.divider} />
          <View style={styles.statusRow}>
            <View style={[styles.statusDot, statusRow.dotColor ? { backgroundColor: statusRow.dotColor } : null]} />
            <Text style={styles.statusText}>{statusRow.label}</Text>
            <Text style={styles.statusTime}>{statusRow.time}</Text>
          </View>
        </>
      ) : null}
    </View>
  );
}
