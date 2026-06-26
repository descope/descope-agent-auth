import typescript from '@rollup/plugin-typescript';
import del from 'rollup-plugin-delete';
import dts from 'rollup-plugin-dts';
import resolve from '@rollup/plugin-node-resolve';
import commonjs from '@rollup/plugin-commonjs';
import json from '@rollup/plugin-json';
import { readFileSync, writeFileSync } from 'fs';

const packageJson = JSON.parse(readFileSync('./package.json', 'utf8'));

// Declarations are emitted by a dedicated `tsc -p tsconfig.build.json` pass into
// dist/types; the JS bundles below only transpile (declaration: false).
const plugins = [
  typescript({ tsconfig: './tsconfig.json', declaration: false, declarationDir: undefined }),
  json(),
  commonjs(),
  resolve(),
];
const input = './src/index.ts';
const external = (id) => !id.startsWith('\0') && !id.startsWith('.') && !id.startsWith('/');

export default [
  {
    input,
    output: { file: packageJson.main, format: 'cjs', sourcemap: true, exports: 'named' },
    plugins,
    external,
  },
  {
    input,
    output: { file: packageJson.module, format: 'esm', sourcemap: true },
    plugins,
    external,
  },
  {
    input: './dist/types/index.d.ts',
    output: [{ file: packageJson.types, format: 'esm' }],
    plugins: [dts(), del({ hook: 'buildEnd', targets: ['./dist/types'] }), cjsPackage()],
  },
];

function cjsPackage() {
  return {
    name: 'cjsPackage',
    buildEnd: () => {
      writeFileSync('./dist/cjs/package.json', JSON.stringify({ type: 'commonjs' }));
    },
  };
}
