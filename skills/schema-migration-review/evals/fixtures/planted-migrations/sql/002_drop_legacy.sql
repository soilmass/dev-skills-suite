-- Planted SQL migration: every risky statement, no down section, no _down.sql
ALTER TABLE orders DROP COLUMN notes;
ALTER TABLE orders ADD COLUMN currency char(3) NOT NULL;
ALTER TABLE orders ALTER COLUMN total TYPE integer;
CREATE INDEX ix_orders_customer ON orders (customer_id);
UPDATE orders SET currency = 'USD';
