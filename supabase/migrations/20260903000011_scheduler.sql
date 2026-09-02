create table if not exists scheduler_state (
    id          int primary key default 1 check (id = 1),
    run_at      text not null,                -- 'HH:MM' local time of the daily freshness run
    next_run_at timestamptz,
    status      text not null,                -- waiting | running
    note        text,
    updated_at  timestamptz not null default now()
);
grant select on scheduler_state to anon, authenticated;
