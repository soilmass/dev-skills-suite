// Minimal reproduction of a false positive found dogfooding this skill
// on actions/checkout (src/git-auth-helper.ts imports './git-command-manager.js'
// even though only git-command-manager.ts exists on disk — TypeScript's
// own ESM/NodeNext convention).
import { b } from './b.js';

export function a(): number {
  return b();
}
