-- Phase 1 email-agent conversation memory schema.
-- Apply this in Supabase SQL editor or through your Supabase migration workflow.

create extension if not exists pgcrypto;

create table if not exists conversation_sessions (
    id uuid primary key default gen_random_uuid(),
    user_id text not null,
    title text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists conversation_messages (
    id uuid primary key default gen_random_uuid(),
    session_id uuid not null references conversation_sessions(id) on delete cascade,
    role text not null check (role in ('user', 'assistant', 'tool', 'system')),
    content text not null,
    metadata jsonb default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists conversation_messages_session_created_idx
    on conversation_messages (session_id, created_at desc);

create table if not exists email_tool_events (
    id uuid primary key default gen_random_uuid(),
    session_id uuid not null references conversation_sessions(id) on delete cascade,
    tool_name text not null,
    tool_args jsonb default '{}'::jsonb,
    tool_result_summary jsonb default '{}'::jsonb,
    success boolean not null default true,
    error text,
    created_at timestamptz not null default now()
);

create index if not exists email_tool_events_session_created_idx
    on email_tool_events (session_id, created_at desc);

create table if not exists draft_events (
    id uuid primary key default gen_random_uuid(),
    session_id uuid not null references conversation_sessions(id) on delete cascade,
    recipient text,
    subject text,
    body text,
    status text not null check (status in ('drafted', 'revised', 'pending_confirmation', 'sent', 'cancelled')),
    metadata jsonb default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists draft_events_session_created_idx
    on draft_events (session_id, created_at desc);

create table if not exists send_events (
    id uuid primary key default gen_random_uuid(),
    session_id uuid not null references conversation_sessions(id) on delete cascade,
    recipient text not null,
    subject text not null,
    confirmed_by_user boolean not null default false,
    sent boolean not null default false,
    send_result jsonb default '{}'::jsonb,
    error text,
    created_at timestamptz not null default now()
);

create index if not exists send_events_session_created_idx
    on send_events (session_id, created_at desc);
