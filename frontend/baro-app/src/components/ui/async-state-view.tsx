import type { ReactNode } from 'react';
import { Text, View, type StyleProp, type ViewStyle } from 'react-native';

import { useThemedStyles } from '@/hooks/use-themed-styles';

import { createStyles } from './async-state-view.styles';

type AsyncStateViewProps = {
  /** 있으면 로딩/에러/빈 상태 문구를 보여주고 children은 그리지 않는다. 없으면 children을 그대로 그린다. */
  message?: string;
  /** 부모가 이미 flex 컨테이너가 아니라 남는 공간을 직접 채워야 할 때만 끈다. */
  fill?: boolean;
  style?: StyleProp<ViewStyle>;
  children: ReactNode;
};

/** 목록 화면의 loading/error/empty 상태를 가운데 정렬된 회색 문구로 통일해서 보여준다. */
export function AsyncStateView({ message, fill = true, style, children }: AsyncStateViewProps) {
  const styles = useThemedStyles(createStyles);

  if (!message) return <>{children}</>;

  return (
    <View style={[styles.container, fill && styles.fill, style]}>
      <Text style={styles.text}>{message}</Text>
    </View>
  );
}
