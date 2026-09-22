import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  css: {
    postcss: {
      plugins: [],
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    // Vitest's 5s default is wall-clock, and the heavy specs (resume-builder-*,
    // resume-viewer-*) mount the whole builder and drive fake timers through 20s
    // of simulated time. They land around 200-400ms each on an idle machine and
    // blow past 5s when the box is busy — the pre-push gate runs them straight
    // after the backend suite, so it saw timeouts no standalone run reproduced.
    // A timeout is a hang detector here, not an assertion; 15s still catches one.
    testTimeout: 15_000,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.'),
    },
  },
});
