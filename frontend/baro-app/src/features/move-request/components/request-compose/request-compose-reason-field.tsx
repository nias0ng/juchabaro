import { TextInput } from 'react-native';

import { Palette } from '@/styles';

import { styles } from './request-compose-reason-field.styles';

type RequestComposeReasonFieldProps = {
  value: string;
  onChangeText: (text: string) => void;
  placeholder?: string;
};

export function RequestComposeReasonField({ value, onChangeText, placeholder }: RequestComposeReasonFieldProps) {
  return (
    <TextInput
      value={value}
      onChangeText={onChangeText}
      placeholder={placeholder}
      placeholderTextColor={Palette.gray400}
      multiline
      textAlignVertical="top"
      autoComplete="off"
      importantForAutofill="no"
      underlineColorAndroid="transparent"
      style={styles.field}
    />
  );
}
