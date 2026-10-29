create table if not exists public.mailboxes (
  user_id bigint primary key,
  chat_id bigint not null,
  address text not null,
  password text not null,
  token text not null,
  created_at double precision not null
);

create table if not exists public.seen (
  user_id bigint not null references public.mailboxes(user_id) on delete cascade,
  msg_id text not null,
  primary key (user_id, msg_id)
);

alter table public.mailboxes enable row level security;
alter table public.seen enable row level security;
