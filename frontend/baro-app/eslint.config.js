// https://docs.expo.dev/guides/using-eslint/
const { defineConfig, globalIgnores } = require('eslint/config');
const expoConfig = require('eslint-config-expo/flat');

// 색상 값을 직접 적은 문자열: #rgb, #rgba, #rrggbb, #rrggbbaa, rgb()/rgba()/hsl()/hsla()
const COLOR_LITERAL = '^(#([0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})|(rgb|hsl)a?\\(.*\\))$';

/**
 * 색은 src/styles의 용도 기반 토큰으로만 쓴다.
 * 이미 옮긴 곳은 오류, 아직 옮기지 않은 곳은 경고로 드러낸다.
 * 기능을 옮길 때마다 TOKENIZED_FILES에 경로를 추가한다.
 */
// 색 속성에 이름으로 적은 색. transparent처럼 색이 아닌 값은 막지 않는다.
const NAMED_COLOR = '^(white|black|red|blue|green|gray|grey|yellow|orange|purple|pink)$';

function colorTokenRules(level, { strict = false } = {}) {
  // 옮긴 경로에서는 옛 의미 토큰(Colors, useTheme)과 Tokens 직접 사용도 막는다.
  // Tokens를 직접 쓰면 AdaptiveColorScope를 건너뛰게 된다.
  const stylesImportNames = strict ? ['Palette', 'Colors', 'Tokens'] : ['Palette'];

  return {
    'no-restricted-syntax': [
      level,
      {
        selector: `TemplateLiteral[expressions.length>0] > TemplateElement[value.raw=/^(rgb|hsl)a?\\(/]`,
        message: '색상 값 대신 src/styles의 토큰을 사용하세요 (useThemedStyles).',
      },
      {
        selector: `Property[key.name=/[cC]olor$/] > Literal[value=/${NAMED_COLOR}/]`,
        message: '색 이름 대신 src/styles의 토큰을 사용하세요 (useThemedStyles).',
      },
      {
        selector: `Literal[value=/${COLOR_LITERAL}/]`,
        message: '색상 값 대신 src/styles의 토큰을 사용하세요 (useThemedStyles).',
      },
      {
        selector: `TemplateElement[value.raw=/${COLOR_LITERAL}/]`,
        message: '색상 값 대신 src/styles의 토큰을 사용하세요 (useThemedStyles).',
      },
    ],
    'no-restricted-imports': [
      level,
      {
        paths: [
          {
            name: '@/styles',
            importNames: stylesImportNames,
            message: '용도 기반 토큰을 useColorTokens / useThemedStyles로 받아 사용하세요.',
          },
          ...(strict
            ? [
                {
                  name: '@/hooks/use-theme',
                  message: 'useTheme 대신 useColorTokens / useThemedStyles를 사용하세요.',
                },
              ]
            : []),
        ],
        patterns: [
          {
            group: ['@/styles/colors', '@/styles/color-tokens', '**/styles/colors', '**/styles/color-tokens'],
            importNames: stylesImportNames,
            message: '용도 기반 토큰을 useColorTokens / useThemedStyles로 받아 사용하세요.',
          },
        ],
      },
    ],
  };
}

const TOKENIZED_FILES = [
  'src/features/move-request/**/*.{ts,tsx}',
  'src/features/design-system/**/*.{ts,tsx}',
  'src/components/ui/screen-header*.{ts,tsx}',
  'src/components/ui/segmented-control*.{ts,tsx}',
  'src/components/ui/gradient-screen-background*.{ts,tsx}',
  'src/components/ui/info-row-card*.{ts,tsx}',
  'src/components/ui/form-section-label*.{ts,tsx}',
  'src/components/ui/async-state-view*.{ts,tsx}',
  'src/components/ui/bottom-nav-bar*.{ts,tsx}',
];

module.exports = defineConfig([
  globalIgnores(['dist/*', '.expo/*']),

  expoConfig,

  {
    files: ['**/*.{ts,tsx}'],
    rules: {
      // 디버깅 로그와 민감한 정보가 남는 것을 방지합니다.
      'no-console': ['warn', { allow: ['warn', 'error'] }],

      // 타입 안정성을 위해 명시적인 any 사용을 경고합니다.
      '@typescript-eslint/no-explicit-any': 'warn',
    },
  },

  {
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/styles/**', '**/*.test.ts', ...TOKENIZED_FILES],
    rules: colorTokenRules('warn'),
  },

  {
    files: TOKENIZED_FILES,
    ignores: ['**/*.test.ts'],
    rules: colorTokenRules('error', { strict: true }),
  },
]);
