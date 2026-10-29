-- =============================================================================
-- NewDoAuto Phase B Migration: Cloud Workflow Persistence & Row Level Security
-- Target: Supabase PostgreSQL
-- Safety: Non-destructive, idempotent creation of public.workflows and RLS.
-- =============================================================================

BEGIN;

-- 1. Create the workflows table
CREATE TABLE IF NOT EXISTS public.workflows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL DEFAULT auth.uid() REFERENCES auth.users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    schema_version TEXT NOT NULL DEFAULT '1.0.0',
    definition JSONB NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT workflows_name_not_blank CHECK (char_length(btrim(name)) > 0),
    CONSTRAINT workflows_schema_version_not_blank CHECK (char_length(btrim(schema_version)) > 0),
    CONSTRAINT workflows_version_positive CHECK (version >= 1),
    CONSTRAINT workflows_definition_is_object CHECK (jsonb_typeof(definition) = 'object'),
    CONSTRAINT workflows_definition_has_actions CHECK (
        definition ? 'actions' AND jsonb_typeof(definition -> 'actions') = 'array'
    )
);

-- 2. Indexes for authenticated user lookup and ordering
CREATE INDEX IF NOT EXISTS idx_workflows_owner_id
    ON public.workflows (owner_id);

CREATE INDEX IF NOT EXISTS idx_workflows_owner_updated_at
    ON public.workflows (owner_id, updated_at DESC);

-- 3. Trigger function to protect immutable columns and maintain updated_at
CREATE OR REPLACE FUNCTION public.handle_workflows_before_update()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
BEGIN
    -- Prevent ownership transfer or tampering with creation timestamp
    IF NEW.owner_id IS DISTINCT FROM OLD.owner_id THEN
        RAISE EXCEPTION 'Changing workflow owner_id is not permitted.';
    END IF;

    IF NEW.id IS DISTINCT FROM OLD.id THEN
        RAISE EXCEPTION 'Changing workflow id is not permitted.';
    END IF;

    NEW.created_at := OLD.created_at;
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_workflows_before_update ON public.workflows;
CREATE TRIGGER trg_workflows_before_update
    BEFORE UPDATE ON public.workflows
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_workflows_before_update();

-- 4. Enable and Force Row Level Security (RLS)
ALTER TABLE public.workflows ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workflows FORCE ROW LEVEL SECURITY;

-- 5. Privilege hardening: deny anonymous access, grant authenticated access
REVOKE ALL ON TABLE public.workflows FROM PUBLIC;
REVOKE ALL ON TABLE public.workflows FROM anon;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.workflows TO authenticated;

-- 6. Row Level Security Policies (strictly scoped to authenticated owner)
DROP POLICY IF EXISTS "workflows_select_own" ON public.workflows;
CREATE POLICY "workflows_select_own"
    ON public.workflows
    FOR SELECT
    TO authenticated
    USING ((SELECT auth.uid()) = owner_id);

DROP POLICY IF EXISTS "workflows_insert_own" ON public.workflows;
CREATE POLICY "workflows_insert_own"
    ON public.workflows
    FOR INSERT
    TO authenticated
    WITH CHECK ((SELECT auth.uid()) = owner_id);

DROP POLICY IF EXISTS "workflows_update_own" ON public.workflows;
CREATE POLICY "workflows_update_own"
    ON public.workflows
    FOR UPDATE
    TO authenticated
    USING ((SELECT auth.uid()) = owner_id)
    WITH CHECK ((SELECT auth.uid()) = owner_id);

DROP POLICY IF EXISTS "workflows_delete_own" ON public.workflows;
CREATE POLICY "workflows_delete_own"
    ON public.workflows
    FOR DELETE
    TO authenticated
    USING ((SELECT auth.uid()) = owner_id);

COMMIT;

