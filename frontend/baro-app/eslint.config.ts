const { defineConfig, globalIgnores } = require('eslint/config');
const expoConfig = require('eslint-config-expo/flat');

module.exports = defineConfig([
  globalIgnores([
    'dist/*',
    '.expo/*',
  ]),

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
]);