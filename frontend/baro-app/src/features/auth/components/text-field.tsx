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

  invalid?: boolean;
  secureTextEntry?: TextInputProps['secureTextEntry'];
  autoCapitalize?: TextInputProps['autoCapitalize'];
  keyboardType?: TextInputProps['keyboardType'];
  autoComplete?: TextInputProps['autoComplete'];
};

export function TextField({
  label,
  value,
  onChangeText,
  placeholder,
  error,
  invalid = false,
  secureTextEntry,
  autoCapitalize = 'none',
  keyboardType,
  autoComplete,
}: TextFieldProps) {
  const theme = useTheme();
  const showErrorBorder = Boolean(error) || invalid;

  return (
    <View style={styles.container}>
      <Text style={styles.label}>{label}</Text>
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
          style={styles.input}
        />
      </View>
      {error ? <Text style={[styles.errorText, { color: theme.danger }]}>{error}</Text> : null}
    </View>
  );
}
