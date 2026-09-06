-- Safe SQL migration: paired down file, concurrent index, default
ALTER TABLE orders ADD COLUMN region char(8) NOT NULL DEFAULT 'eu';
CREATE INDEX CONCURRENTLY ix_orders_region ON orders (region);
