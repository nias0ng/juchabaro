import assert from 'node:assert/strict';
import { test } from 'node:test';

import { Tokens, type ColorTokens } from './color-tokens';
import { checkContrast, contrastRatio } from './contrast';

function keyPaths(value: unknown, prefix = ''): string[] {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return [prefix];
  return Object.entries(value).flatMap(([key, child]) => keyPaths(child, prefix ? `${prefix}.${key}` : key));
}

test('contrastRatio는 WCAG 공식 값을 낸다', () => {
  assert.equal(contrastRatio('#000000', '#ffffff').toFixed(2), '21.00');
  assert.equal(contrastRatio('#9599a7', '#ffffff').toFixed(2), '2.84');
  assert.equal(contrastRatio('#60646c', '#ffffff').toFixed(2), '5.94');
});

test('라이트 토큰은 예외를 빼면 AA 미달이 없다', () => {
  assert.deepEqual(
    checkContrast(Tokens.light, 'light').filter((failure) => !failure.excepted),
    [],
  );
});

test('다크 토큰은 예외를 빼면 AA 미달이 없다', () => {
  assert.deepEqual(
    checkContrast(Tokens.dark, 'dark').filter((failure) => !failure.excepted),
    [],
  );
});

test('라이트와 다크는 같은 키를 갖는다', () => {
  assert.deepEqual(keyPaths(Tokens.light), keyPaths(Tokens.dark));
});

test('옛 보조 글자색은 검사에 걸린다', () => {
  const old: ColorTokens = { ...Tokens.light, text: { ...Tokens.light.text, weaker: '#9599a7' } };
  assert.ok(checkContrast(old, 'light').some((failure) => failure.name.startsWith('text.weaker')));
});

test('옛 배지 글자색은 옅은 배경 위에서 검사에 걸린다', () => {
  const old: ColorTokens = { ...Tokens.light, text: { ...Tokens.light.text, info: '#3f7bd6' } };
  assert.ok(checkContrast(old, 'light').some((failure) => failure.name === 'text.info on fill.info.weak'));
});
