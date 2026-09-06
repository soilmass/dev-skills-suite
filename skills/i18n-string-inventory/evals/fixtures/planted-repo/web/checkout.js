// Checkout page strings.
import { t } from "./i18n";

export function render(items) {
  const title = t("checkout.title");
  const count = t("cart.items", { count: items.length });
  return `<h1>${title}</h1><p>${count}</p>`;
}

export function payButton() {
  // checkout.pay is referenced here and in app/checkout.py but never
  // added to en.json — the planted missing key.
  return `<button>${t("checkout.pay")}</button>`;
}
