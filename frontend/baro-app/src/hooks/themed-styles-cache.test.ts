import assert from 'node:assert/strict';
import { test } from 'node:test';

import { Tokens, type ColorTokens } from '../styles/color-tokens';
import { getThemedStyles } from './themed-styles-cache';

test('같은 create와 같은 토큰이면 한 번만 만든다', () => {
  let calls = 0;
  const create = (t: ColorTokens) => {
    calls += 1;
    return { c: t.text.strong };
  };

  const a = getThemedStyles(create, Tokens.light);
  const b = getThemedStyles(create, Tokens.light);

  assert.equal(a, b);
  assert.equal(calls, 1);
});

test('토큰이 바뀌면 그 모드의 값을 돌려준다', () => {
  const create = (t: ColorTokens) => ({ c: t.text.strong });

  assert.equal(getThemedStyles(create, Tokens.light).c, Tokens.light.text.strong);
  assert.equal(getThemedStyles(create, Tokens.dark).c, Tokens.dark.text.strong);
});

test('다크를 만든 뒤에도 라이트 결과는 그대로다', () => {
  const create = (t: ColorTokens) => ({ c: t.text.strong });
  const light = getThemedStyles(create, Tokens.light);

  getThemedStyles(create, Tokens.dark);

  assert.equal(getThemedStyles(create, Tokens.light), light);
});
