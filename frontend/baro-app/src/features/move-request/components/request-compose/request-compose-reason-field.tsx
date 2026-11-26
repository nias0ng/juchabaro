import { TextInput } from 'react-native';

import { useColorTokens } from '@/hooks/use-color-tokens';
import { useThemedStyles } from '@/hooks/use-themed-styles';

import { createStyles } from './request-compose-reason-field.styles';

type RequestComposeReasonFieldProps = {
  value: string;
  onChangeText: (text: string) => void;
  placeholder?: string;
};

export function RequestComposeReasonField({ value, onChangeText, placeholder }: RequestComposeReasonFieldProps) {
  const styles = useThemedStyles(createStyles);
  const t = useColorTokens();

  return (
    <TextInput
      value={value}
      onChangeText={onChangeText}
      placeholder={placeholder}
      placeholderTextColor={t.text.weaker}
      multiline
      textAlignVertical="top"
      autoComplete="off"
      importantForAutofill="no"
      underlineColorAndroid="transparent"
      style={styles.field}
    />
  );
}
