// Planted fixture: JavaScript reads in three shapes.
const port = process.env.PORT || 3000;
const dsn = process.env["SENTRY_DSN"];
const flags = process.env.FEATURE_FLAGS ?? "";
const db = process.env.DATABASE_URL;
module.exports = { port, dsn, flags, db };
