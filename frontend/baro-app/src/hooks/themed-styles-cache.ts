import type { ColorTokens } from '@/styles/color-tokens';

type CreateStyles<T> = (tokens: ColorTokens) => T;

const cache = new WeakMap<CreateStyles<unknown>, WeakMap<ColorTokens, unknown>>();

/**
 * (create, tokens) 쌍마다 스타일을 한 번만 만든다.
 * 모드는 라이트/다크 둘뿐이라 create 하나당 최대 두 번 호출된다.
 * create는 모듈 최상위에 정의해야 한다. 컴포넌트 안에서 만들면 매번 새 함수라 캐시가 듣지 않는다.
 */
export function getThemedStyles<T>(create: CreateStyles<T>, tokens: ColorTokens): T {
  let byTokens = cache.get(create);
  if (!byTokens) {
    byTokens = new WeakMap();
    cache.set(create, byTokens);
  }

  if (!byTokens.has(tokens)) {
    byTokens.set(tokens, create(tokens));
  }

  return byTokens.get(tokens) as T;
}
