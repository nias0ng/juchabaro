import { Text } from 'react-native';

import { Stack } from '@/components/ui';
import { Spacing } from '@/styles';

import { styles } from './signup-step-heading.styles';

type SignupStepHeadingProps = {
  title: string;
  description: string;
};

export function SignupStepHeading({ title, description }: SignupStepHeadingProps) {
  return (
    <Stack gap={Spacing.xs}>
      <Text style={styles.title}>{title}</Text>
      <Text style={styles.description}>{description}</Text>
    </Stack>
  );
}
