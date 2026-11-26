import assert from 'node:assert/strict';
import { test } from 'node:test';

import { Tokens } from '../styles/color-tokens';
import { resolveColorTokens } from './resolve-color-tokens';

test('적용 범위 안에서 기기가 다크면 다크 토큰을 준다', () => {
  assert.equal(resolveColorTokens(true, 'dark'), Tokens.dark);
});

test('적용 범위 안이라도 기기가 라이트면 라이트 토큰을 준다', () => {
  assert.equal(resolveColorTokens(true, 'light'), Tokens.light);
});

test('적용 범위 밖에서는 기기가 다크여도 라이트 토큰을 준다', () => {
  assert.equal(resolveColorTokens(false, 'dark'), Tokens.light);
});

test('기기 모드를 알 수 없으면 라이트 토큰을 준다', () => {
  assert.equal(resolveColorTokens(true, null), Tokens.light);
  assert.equal(resolveColorTokens(true, undefined), Tokens.light);
});
