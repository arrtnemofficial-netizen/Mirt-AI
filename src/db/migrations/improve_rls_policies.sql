-- Improve Row Level Security (RLS) policies
-- Add explicit policies for all tables and operations

-- ============================================================================
-- PRODUCTS TABLE POLICIES
-- ============================================================================

-- Drop existing policy if it exists (idempotent)
drop policy if exists "Public products read access" on products;

-- Allow read access to products for everyone (public catalog)
create policy "Public products read access" 
on products for select 
using (true);

-- Allow service role full access (insert, update, delete)
-- Note: Service role bypasses RLS, but explicit policy is good practice
create policy "Service role full access" 
on products for all
using (current_setting('role') = 'service_role')
with check (current_setting('role') = 'service_role');

-- ============================================================================
-- ORDERS TABLE POLICIES
-- ============================================================================

-- Users can only see their own orders
create policy "Users can view own orders" 
on orders for select
using (auth.uid()::text = user_id OR current_setting('role') = 'service_role');

-- Users can insert their own orders
create policy "Users can create own orders" 
on orders for insert
with check (auth.uid()::text = user_id OR current_setting('role') = 'service_role');

-- Only service role can update/delete orders
create policy "Service role can modify orders" 
on orders for all
using (current_setting('role') = 'service_role')
with check (current_setting('role') = 'service_role');

-- ============================================================================
-- ORDER_ITEMS TABLE POLICIES
-- ============================================================================

-- Users can view items of their own orders
create policy "Users can view own order items" 
on order_items for select
using (
    exists (
        select 1 from orders 
        where orders.id = order_items.order_id 
        and (orders.user_id = auth.uid()::text OR current_setting('role') = 'service_role')
    )
);

-- Users can insert items to their own orders
create policy "Users can create own order items" 
on order_items for insert
with check (
    exists (
        select 1 from orders 
        where orders.id = order_items.order_id 
        and (orders.user_id = auth.uid()::text OR current_setting('role') = 'service_role')
    )
);

-- Only service role can update/delete order items
create policy "Service role can modify order items" 
on order_items for all
using (current_setting('role') = 'service_role')
with check (current_setting('role') = 'service_role');

-- ============================================================================
-- CRM_ORDERS TABLE POLICIES
-- ============================================================================

-- Only service role can access CRM orders (internal table)
create policy "Service role only access" 
on crm_orders for all
using (current_setting('role') = 'service_role')
with check (current_setting('role') = 'service_role');

-- ============================================================================
-- NOTES
-- ============================================================================
-- 
-- These policies assume:
-- 1. Supabase Auth is configured with user IDs matching user_id in orders table
-- 2. Service role is used for backend operations
-- 3. If using anon key, adjust policies accordingly
-- 
-- To test policies:
-- SET ROLE service_role;
-- SELECT * FROM orders; -- Should work
-- 
-- SET ROLE authenticated;
-- SET request.jwt.claim.sub = 'user_id_here';
-- SELECT * FROM orders; -- Should only see own orders

