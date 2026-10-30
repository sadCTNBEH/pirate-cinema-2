import js from '@eslint/js';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    ignores: ['dist/**', 'node_modules/**', 'public/**'],
  },
  {
    files: ['**/*.{ts,tsx,js,jsx}'],
    rules: {
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      'no-unused-vars': 'off',
      'no-undef': 'off',
      'no-empty': ['error', { allowEmptyCatch: true }],
      'preserve-caught-error': 'warn',
      'no-useless-assignment': 'warn',
      'no-useless-escape': 'warn',
    },
  }
);
