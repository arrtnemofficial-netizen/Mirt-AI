-- CRM Orders Table Schema for Supabase
-- Stores mapping between chat sessions and CRM orders with status tracking

CREATE TABLE IF NOT EXISTS crm_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL,                    -- Telegram/ManyChat session ID
    external_id TEXT NOT NULL UNIQUE,           -- Unique order identifier (session_timestamp)
    crm_order_id TEXT,                          -- Order ID from Snitkix CRM
    status TEXT NOT NULL DEFAULT 'pending',     -- pending, queued, created, processing, shipped, delivered, cancelled, failed
    order_data JSONB,                           -- Full order data (customer, items, etc.)
    metadata JSONB,                             -- Additional metadata from CRM webhooks
    task_id TEXT,                               -- Celery task ID for async operations
    error_message TEXT,                         -- Error details if failed
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT crm_orders_status_check CHECK (status IN (
        'pending', 'queued', 'created', 'processing', 
        'shipped', 'delivered', 'cancelled', 'failed'
    ))
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_crm_orders_session_id ON crm_orders(session_id);
CREATE INDEX IF NOT EXISTS idx_crm_orders_external_id ON crm_orders(external_id);
CREATE INDEX IF NOT EXISTS idx_crm_orders_crm_order_id ON crm_orders(crm_order_id);
CREATE INDEX IF NOT EXISTS idx_crm_orders_status ON crm_orders(status);
CREATE INDEX IF NOT EXISTS idx_crm_orders_created_at ON crm_orders(created_at DESC);

-- RLS (Row Level Security) policies if needed for multi-tenant
-- ALTER TABLE crm_orders ENABLE ROW LEVEL SECURITY;

-- Function to automatically update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger to auto-update updated_at
CREATE TRIGGER update_crm_orders_updated_at 
    BEFORE UPDATE ON crm_orders 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- Comments for documentation
COMMENT ON TABLE crm_orders IS 'Maps chat sessions to CRM orders with status tracking';
COMMENT ON COLUMN crm_orders.session_id IS 'Telegram/ManyChat session identifier';
COMMENT ON COLUMN crm_orders.external_id IS 'Unique order identifier to prevent duplicates';
COMMENT ON COLUMN crm_orders.crm_order_id IS 'Order ID from external CRM system (Snitkix)';
COMMENT ON COLUMN crm_orders.status IS 'Current order status in the system';
COMMENT ON COLUMN crm_orders.order_data IS 'Complete order data including customer and items';
COMMENT ON COLUMN crm_orders.metadata IS 'Additional metadata from CRM webhooks and updates';
