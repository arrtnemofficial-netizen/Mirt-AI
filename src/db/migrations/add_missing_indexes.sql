-- Add missing indexes for performance optimization
-- Run this migration to improve query performance on timestamp fields

-- Indexes for orders table
create index if not exists idx_orders_created_at on orders(created_at);
create index if not exists idx_orders_updated_at on orders(updated_at);
create index if not exists idx_orders_status on orders(status);
create index if not exists idx_orders_status_created_at on orders(status, created_at);

-- Indexes for crm_orders table
create index if not exists idx_crm_orders_created_at on crm_orders(created_at);
create index if not exists idx_crm_orders_updated_at on crm_orders(updated_at);
create index if not exists idx_crm_orders_session_id on crm_orders(session_id);
create index if not exists idx_crm_orders_status_updated_at on crm_orders(status, updated_at);

-- Indexes for order_items table
create index if not exists idx_order_items_product_id on order_items(product_id);
create index if not exists idx_order_items_created_at on order_items(created_at);

-- Indexes for products table (if not already present)
create index if not exists idx_products_created_at on products(created_at);
create index if not exists idx_products_updated_at on products(updated_at);
create index if not exists idx_products_category_subcategory on products(category, subcategory);

