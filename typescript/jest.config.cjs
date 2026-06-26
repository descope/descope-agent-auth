module.exports = {
  clearMocks: true,
  watchman: false,

  collectCoverage: true,
  coverageDirectory: 'coverage',
  collectCoverageFrom: [
    'src/**/*.{js,jsx,ts,tsx}',
    '!src/**/*.test.ts',
    '!src/testutils.ts',
    '!src/**/index.ts',
  ],
  coverageThreshold: {
    global: {
      branches: 65,
      functions: 85,
      lines: 88,
      statements: 85,
    },
  },

  preset: 'ts-jest',
  testEnvironment: 'node',
  moduleDirectories: ['node_modules', 'src'],

  testTimeout: 5000,

  roots: ['src'],
};
