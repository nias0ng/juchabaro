import type { ReactNode } from 'react';
import { Pressable, Text, TextInput, View, type TextInputProps } from 'react-native';

import { useTheme } from '@/hooks/use-theme';
import { Palette } from '@/styles';

import { styles } from './text-field.styles';

type TextFieldProps = {
  label: string;
  value: string;
  onChangeText: (text: string) => void;
  placeholder?: string;
  error?: string;
  invalid?: boolean;
  helperText?: string;
  rightAdornment?: ReactNode;
  secureTextEntry?: TextInputProps['secureTextEntry'];
  autoCapitalize?: TextInputProps['autoCapitalize'];
  keyboardType?: TextInputProps['keyboardType'];
  autoComplete?: TextInputProps['autoComplete'];
  maxLength?: TextInputProps['maxLength'];
  /** false면 키보드로 값을 수정할 수 없다. 날짜 선택처럼 다른 UI로 값을 채우는 필드에 사용한다. */
  editable?: boolean;
  /** 지정하면 필드 전체가 눌렀을 때 이 콜백을 호출하는 버튼처럼 동작한다(예: date picker 열기). */
  onPress?: () => void;
};

export function TextField({
  label,
  value,
  onChangeText,
  placeholder,
  error,
  invalid = false,
  helperText,
  rightAdornment,
  secureTextEntry,
  autoCapitalize = 'none',
  keyboardType,
  autoComplete,
  maxLength,
  editable = true,
  onPress,
}: TextFieldProps) {
  const theme = useTheme();
  const showErrorBorder = Boolean(error) || invalid;

  const field = (
    <View
      style={[
        styles.field,
        showErrorBorder && [styles.fieldError, { borderColor: theme.dangerBorder }],
      ]}
    >
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={Palette.gray400}
        secureTextEntry={secureTextEntry}
        autoCapitalize={autoCapitalize}
        keyboardType={keyboardType}
        autoComplete={autoComplete}
        maxLength={maxLength}
        editable={editable}
        style={styles.input}
      />
      {rightAdornment}
    </View>
  );

  return (
    <View style={styles.container}>
      <Text style={styles.label}>{label}</Text>
      {onPress ? (
        <Pressable accessibilityRole="button" onPress={onPress}>
          {field}
        </Pressable>
      ) : (
        field
      )}
      {error ? (
        <Text style={[styles.errorText, { color: theme.danger }]}>{error}</Text>
      ) : helperText ? (
        <Text style={[styles.errorText, { color: Palette.gray500 }]}>{helperText}</Text>
      ) : null}
    </View>
  );
}
