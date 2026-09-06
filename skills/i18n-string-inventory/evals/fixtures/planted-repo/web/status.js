import { t } from "./i18n";

export function statusLabel(s) {
  // Built at runtime — the inventory cannot see which keys it needs.
  return t(`status.${s}`);
}
