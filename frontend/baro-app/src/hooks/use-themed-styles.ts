import { useColorTokens } from '@/hooks/use-color-tokens';
import type { ColorTokens } from '@/styles';

import { getThemedStyles } from './themed-styles-cache';

/**
 * `*.styles.ts`의 `createStyles(t)`를 현재 모드의 스타일로 바꿔 준다.
 *
 * ```ts
 * // foo.styles.ts
 * export const createStyles = (t: ColorTokens) => StyleSheet.create({ label: { color: t.text.weak } });
 * // foo.tsx
 * const styles = useThemedStyles(createStyles);
 * ```
 */
export function useThemedStyles<T>(create: (tokens: ColorTokens) => T): T {
  return getThemedStyles(create, useColorTokens());
}
