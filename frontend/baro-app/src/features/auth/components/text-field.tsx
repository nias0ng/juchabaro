import type { ReactNode } from 'react';
import { Text, TextInput, View, type TextInputProps } from 'react-native';

import { useTheme } from '@/hooks/use-theme';
import { Palette } from '@/styles';

import { styles } from './text-field.styles';

type TextFieldProps = {
  label: string;
  value: string;
  onChangeText: (text: string) => void;
  placeholder?: string;
  error?: string;
  helperText?: string;
  rightAdornment?: ReactNode;
  secureTextEntry?: TextInputProps['secureTextEntry'];
  autoCapitalize?: TextInputProps['autoCapitalize'];
  keyboardType?: TextInputProps['keyboardType'];
  autoComplete?: TextInputProps['autoComplete'];
  maxLength?: TextInputProps['maxLength'];
};

export function TextField({
  label,
  value,
  onChangeText,
  placeholder,
  error,
  helperText,
  rightAdornment,
  secureTextEntry,
  autoCapitalize = 'none',
  keyboardType,
  autoComplete,
  maxLength,
}: TextFieldProps) {
  const theme = useTheme();

  return (
    <View style={styles.container}>
      <Text style={styles.label}>{label}</Text>
      <View style={[styles.field, error && [styles.fieldError, { borderColor: theme.dangerBorder }]]}>
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
          style={styles.input}
        />
        {rightAdornment}
      </View>
      {error ? (
        <Text style={[styles.errorText, { color: theme.danger }]}>{error}</Text>
      ) : helperText ? (
        <Text style={[styles.errorText, { color: Palette.gray500 }]}>{helperText}</Text>
      ) : null}
    </View>
  );
}
