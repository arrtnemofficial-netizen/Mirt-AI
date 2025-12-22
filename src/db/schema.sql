-- Enable pgvector extension for semantic search
create extension if not exists vector;

-- ============================================================================
-- PRODUCTS TABLE
-- ============================================================================
create table if not exists products (
    id bigint primary key generated always as identity,
    name text not null,
    description text,
    category text not null,
    subcategory text,
    price numeric(10, 2) not null,
    sizes text[] not null default '{}', -- Array of available sizes
    colors text[] not null default '{}', -- Array of available colors
    photo_url text,
    sku text unique,
    
    -- Metadata
    created_at timestamptz default now(),
    updated_at timestamptz default now(),
    
    -- Vector embedding for semantic search (e.g. "pink dress for school")
    embedding vector(1536) -- Compatible with text-embedding-3-small
);

-- Indexes for faster search
create index if not exists idx_products_category on products(category);
create index if not exists idx_products_price on products(price);

-- ============================================================================
-- ORDERS TABLE
-- ============================================================================
create table if not exists orders (
    id bigint primary key generated always as identity,
    user_id text not null, -- External ID (Telegram/ManyChat ID)
    session_id text not null, -- Conversation session ID
    
    -- Customer Info
    customer_name text,
    customer_phone text,
    customer_city text,
    delivery_method text,
    delivery_address text, -- Nova Poshta branch
    
    -- Order Details
    status text not null default 'new', -- new, paid, shipped, cancelled
    total_amount numeric(10, 2) not null default 0,
    currency text default 'UAH',
    
    -- Metadata
    created_at timestamptz default now(),
    updated_at timestamptz default now(),
    notes text
);

create index if not exists idx_orders_user_id on orders(user_id);
create index if not exists idx_orders_session_id on orders(session_id);

-- ============================================================================
-- ORDER ITEMS TABLE
-- ============================================================================
create table if not exists order_items (
    id bigint primary key generated always as identity,
    order_id bigint references orders(id) on delete cascade,
    product_id bigint references products(id),
    
    product_name text not null, -- Snapshot of name at time of order
    quantity int not null default 1,
    price_at_purchase numeric(10, 2) not null, -- Snapshot of price
    
    selected_size text,
    selected_color text,
    
    created_at timestamptz default now()
);

create index if not exists idx_order_items_order_id on order_items(order_id);

-- ============================================================================
-- CRM ORDERS TABLE (mapping external_id -> CRM order with idempotency)
-- ============================================================================
create table if not exists crm_orders (
    id bigint primary key generated always as identity,
    session_id text not null,
    external_id text not null,
    crm_order_id text,
    status text not null default 'pending',
    task_id text,
    order_data jsonb,
    metadata jsonb,
    error_message text,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create unique index if not exists ux_crm_orders_external_id on crm_orders(external_id);
create index if not exists idx_crm_orders_status on crm_orders(status);

-- ============================================================================
-- RLS POLICIES (Row Level Security)
-- ============================================================================
alter table products enable row level security;
alter table orders enable row level security;
alter table order_items enable row level security;
alter table crm_orders enable row level security;

-- Allow read access to products for everyone (public catalog)
create policy "Public products read access" 
on products for select 
using (true);

-- Allow service role full access (for admin/bot)
-- Note: Service role bypasses RLS, but explicit policies are good practice.
