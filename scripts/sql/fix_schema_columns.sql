-- ============================================================================
-- FIX MISSING COLUMNS IN MESSAGES AND USERS
-- ============================================================================

-- MESSAGES: Add missing columns
ALTER TABLE messages ADD COLUMN IF NOT EXISTS user_id TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS content_type TEXT DEFAULT 'text';
ALTER TABLE messages ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id) WHERE user_id IS NOT NULL;

-- USERS: Add missing columns (rename id to user_id if needed)
DO $$
BEGIN
    -- Add user_id column if not exists
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'users' AND table_schema = 'public' AND column_name = 'user_id') THEN
        -- Check if we need to rename id or create new column
        ALTER TABLE users ADD COLUMN user_id TEXT;
        -- Copy id to user_id if id is text
        UPDATE users SET user_id = id WHERE user_id IS NULL;
        RAISE NOTICE '✅ Added users.user_id';
    END IF;
END $$;

ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_interaction_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE users ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT '{}';

-- Add unique constraint on user_id if not exists
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_user_id_key') THEN
        ALTER TABLE users ADD CONSTRAINT users_user_id_key UNIQUE (user_id);
        RAISE NOTICE '✅ Added unique constraint on users.user_id';
    END IF;
EXCEPTION
    WHEN duplicate_object THEN
        RAISE NOTICE '⏭️ Constraint already exists';
END $$;

CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_users_last_interaction ON users(last_interaction_at DESC);

-- Verification
DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '============================================';
    RAISE NOTICE '✅ SCHEMA FIX COMPLETE!';
    RAISE NOTICE '============================================';
END $$;
