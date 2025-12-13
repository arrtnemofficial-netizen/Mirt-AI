-- Migration: Add sitniks_chat_id to link MIRT users with Sitniks CRM chats
-- Run this in Supabase SQL Editor

-- 1. Add sitniks_chat_id to mirt_profiles (if you use memory system)
ALTER TABLE mirt_profiles 
ADD COLUMN IF NOT EXISTS sitniks_chat_id TEXT;

-- 2. Add sitniks_chat_id to orders table for order-level tracking
ALTER TABLE orders
ADD COLUMN IF NOT EXISTS sitniks_chat_id TEXT;

-- 3. Create index for fast lookup
CREATE INDEX IF NOT EXISTS idx_mirt_profiles_sitniks_chat_id 
ON mirt_profiles(sitniks_chat_id) 
WHERE sitniks_chat_id IS NOT NULL;

-- 4. Add user_nickname column to orders if not exists
ALTER TABLE orders
ADD COLUMN IF NOT EXISTS user_nickname TEXT;

-- 5. Create a dedicated table for Sitniks chat mappings (alternative approach)
CREATE TABLE IF NOT EXISTS sitniks_chat_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    instagram_username TEXT,
    telegram_username TEXT,
    sitniks_chat_id TEXT UNIQUE,
    sitniks_manager_id INTEGER,
    current_status TEXT,
    first_touch_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sitniks_mappings_user_id ON sitniks_chat_mappings(user_id);
CREATE INDEX IF NOT EXISTS idx_sitniks_mappings_instagram ON sitniks_chat_mappings(instagram_username);
CREATE INDEX IF NOT EXISTS idx_sitniks_mappings_telegram ON sitniks_chat_mappings(telegram_username);

COMMENT ON TABLE sitniks_chat_mappings IS 'Links MIRT users to Sitniks CRM chat IDs for status updates';
