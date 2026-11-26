import { Tokens, type ColorTokens } from '@/styles/color-tokens';

/**
 * 다크 토큰은 "적용 범위" 안에서만 준다.
 *
 * 공용 컴포넌트(헤더, 배경 등)는 아직 새 토큰으로 옮기지 않은 화면에서도 쓰인다.
 * 그런 화면은 글자색이 라이트로 고정되어 있어서, 공용 컴포넌트만 다크로 바뀌면 글자가 배경에 묻힌다.
 * 그래서 화면이 통째로 옮겨졌다고 선언한 범위(AdaptiveColorScope) 안에서만 기기 모드를 따른다.
 */
export function resolveColorTokens(adaptive: boolean, scheme: string | null | undefined): ColorTokens {
  return adaptive && scheme === 'dark' ? Tokens.dark : Tokens.light;
}
