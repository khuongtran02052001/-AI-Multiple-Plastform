-- khuoqtd Publisher: backend-only tables; no browser/Data API grants.

-- Run only in the selected project SQL Editor, or let app startup create tables.

-- Existing tables are not altered to repair an incompatible schema.

BEGIN;

SET LOCAL search_path = public;

CREATE TABLE IF NOT EXISTS sp_accounts (
	id VARCHAR(36) NOT NULL, 
	provider VARCHAR(20) NOT NULL, 
	external_id VARCHAR(128) NOT NULL, 
	name VARCHAR(300) NOT NULL, 
	tokens TEXT NOT NULL, 
	active BOOLEAN NOT NULL, 
	created_at FLOAT NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (provider, external_id)
);

CREATE TABLE IF NOT EXISTS sp_media (
	id VARCHAR(36) NOT NULL, 
	filename VARCHAR(200) NOT NULL, 
	path TEXT NOT NULL, 
	size INTEGER NOT NULL, 
	duration FLOAT NOT NULL, 
	width INTEGER NOT NULL, 
	height INTEGER NOT NULL, 
	created_at FLOAT NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS sp_oauth_states (
	id VARCHAR(64) NOT NULL, 
	session_id VARCHAR(64) NOT NULL, 
	provider VARCHAR(20) NOT NULL, 
	verifier TEXT NOT NULL, 
	expires_at FLOAT NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS sp_sessions (
	id VARCHAR(64) NOT NULL, 
	csrf VARCHAR(64) NOT NULL, 
	expires_at FLOAT NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS sp_posts (
	id VARCHAR(36) NOT NULL, 
	batch_key VARCHAR(100) NOT NULL, 
	account_id VARCHAR(36) NOT NULL, 
	media_id VARCHAR(36), 
	title VARCHAR(100) NOT NULL, 
	description TEXT NOT NULL, 
	tags TEXT NOT NULL, 
	privacy VARCHAR(20) NOT NULL, 
	made_for_kids BOOLEAN NOT NULL, 
	shorts BOOLEAN NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	scheduled_at FLOAT NOT NULL, 
	created_at FLOAT NOT NULL, 
	updated_at FLOAT NOT NULL, 
	remote_id VARCHAR(150), 
	remote_url TEXT, 
	error TEXT, 
	lease_until FLOAT, 
	PRIMARY KEY (id), 
	UNIQUE (batch_key, account_id), 
	FOREIGN KEY(account_id) REFERENCES sp_accounts (id), 
	FOREIGN KEY(media_id) REFERENCES sp_media (id)
);

-- One idempotent import request per Telegram/n8n message; video files remain on VPS.
CREATE TABLE IF NOT EXISTS sp_ingests (
    id VARCHAR(36) PRIMARY KEY,
    request_key VARCHAR(100) NOT NULL UNIQUE,
    telegram_chat_id VARCHAR(32) NOT NULL,
    notified_at FLOAT,
    source_url TEXT NOT NULL,
    account_id VARCHAR(36) NOT NULL REFERENCES sp_accounts(id),
    title VARCHAR(100) NOT NULL,
    description TEXT NOT NULL,
    made_for_kids BOOLEAN NOT NULL,
    status VARCHAR(30) NOT NULL,
    scheduled_at FLOAT NOT NULL,
    created_at FLOAT NOT NULL,
    updated_at FLOAT NOT NULL,
    post_id VARCHAR(36),
    error TEXT,
    lease_until FLOAT
);

CREATE INDEX IF NOT EXISTS sp_ingests_due_idx
    ON sp_ingests (status, created_at);
ALTER TABLE public.sp_ingests ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.sp_ingests FROM PUBLIC, anon, authenticated;

ALTER TABLE public.sp_accounts ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.sp_accounts FROM PUBLIC, anon, authenticated;

ALTER TABLE public.sp_media ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.sp_media FROM PUBLIC, anon, authenticated;

ALTER TABLE public.sp_oauth_states ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.sp_oauth_states FROM PUBLIC, anon, authenticated;

ALTER TABLE public.sp_sessions ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.sp_sessions FROM PUBLIC, anon, authenticated;

CREATE INDEX IF NOT EXISTS sp_posts_due_idx ON sp_posts (status, scheduled_at);

ALTER TABLE public.sp_posts ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.sp_posts FROM PUBLIC, anon, authenticated;

COMMIT;
