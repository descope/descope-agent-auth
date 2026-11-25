import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    include: ['src/**/*.test.ts'],
    clearMocks: true,
    testTimeout: 5000,
    coverage: {
      enabled: true,
      provider: 'v8',
      include: ['src/**/*.ts'],
      exclude: ['src/**/*.test.ts', 'src/testutils.ts', 'src/**/index.ts'],
      thresholds: {
        branches: 65,
        functions: 85,
        lines: 88,
        statements: 85,
      },
    },
  },
});
