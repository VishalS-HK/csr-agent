-- 0001: schemas, extensions and access rules.
--
-- app       -> application tables (customers, orders, refunds, ...)
-- langgraph -> LangGraph checkpoint tables (created by the checkpointer in week 2)
--
-- Neither schema is exposed by Supabase's REST API (only `public` is by default),
-- and only FastAPI -- connecting as the `postgres` role -- may use them.

create schema if not exists app;
create schema if not exists langgraph;

-- pgvector, for policy chunk embeddings. Supabase keeps extensions in the
-- `extensions` schema, so the column type is `extensions.vector(1536)`.
create extension if not exists vector with schema extensions;

-- Lock out Supabase's API roles.
revoke all on schema app, langgraph from anon, authenticated;

-- ...including for objects created later (by this migration role).
alter default privileges in schema app, langgraph
    revoke all on tables from anon, authenticated;
alter default privileges in schema app, langgraph
    revoke all on sequences from anon, authenticated;
alter default privileges in schema app, langgraph
    revoke all on functions from public, anon, authenticated;
