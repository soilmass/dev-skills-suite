// Planted fixture: JavaScript flag checks, including an unregistered one.
const newCheckout = useFlag("new-checkout");
const ghost = isEnabled("ghost-mode");
const partial = client.variation("partial", false);
export { newCheckout, ghost, partial };
