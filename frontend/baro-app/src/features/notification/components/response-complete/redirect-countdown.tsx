import { Text, View } from 'react-native';

import { styles } from './redirect-countdown.styles';

type RedirectCountdownProps = {
  secondsLeft: number;
};

export function RedirectCountdown({ secondsLeft }: RedirectCountdownProps) {
  return (
    <View style={styles.pill}>
      <Text style={styles.text}>
        10초 후에{'  '}이동 요청 페이지로 이동합니다.{'\n'}
        {secondsLeft}...
      </Text>
    </View>
  );
}
