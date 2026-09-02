-- Stage 3 (collect_text) raw Reddit posts and comments. Append/upsert only.

create table if not exists raw_posts (
    id           bigserial primary key,
    reddit_id    text        not null unique,     -- e.g. '1abc23'
    subreddit    text        not null,
    title        text        not null,
    selftext     text,
    author       text,
    score        int,
    num_comments int,
    created_utc  timestamptz,
    permalink    text,
    queries      text[]      not null default '{}',   -- which (subreddit, keyword) searches surfaced it
    content_hash text        not null,
    fetched_at   timestamptz not null default now(),
    comments_fetched_at timestamptz
);
create index if not exists raw_posts_subreddit_idx on raw_posts (subreddit, created_utc desc);

create table if not exists raw_comments (
    id           bigserial primary key,
    reddit_id    text        not null unique,
    post_reddit_id text      not null references raw_posts (reddit_id),
    parent_id    text,                              -- 't3_<post>' or 't1_<comment>'
    author       text,
    body         text        not null,
    score        int,
    depth        int,
    created_utc  timestamptz,
    content_hash text        not null,              -- downstream stages skip unchanged hashes
    fetched_at   timestamptz not null default now()
);
create index if not exists raw_comments_post_idx on raw_comments (post_reddit_id);
