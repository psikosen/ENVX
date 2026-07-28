-- envx v2.1 migration 006 — graph nodes.
--
-- Migration 005 created graph_edges but not the nodes. Node labels and types
-- cannot be derived from edges: an edge knows two ids and a relation, not
-- that "entity:abc" is a canonical seller displayed as "ACME Housing LLC".
--
-- node_id is the application-level composite id ("entity:<uuid>",
-- "doc:<sha>", "risk:asbestos") rather than a generated uuid, so the graph
-- can be rebuilt into memory without an id translation pass.

CREATE TABLE IF NOT EXISTS graph_nodes (
    node_id      text PRIMARY KEY,
    node_type    text NOT NULL CHECK (node_type IN ('entity', 'document', 'risk')),
    label        text NOT NULL,
    attributes   jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS graph_nodes_type ON graph_nodes (node_type);
CREATE INDEX IF NOT EXISTS graph_nodes_label ON graph_nodes (lower(label));

-- graph_edges endpoints reference graph_nodes. Not declared as foreign keys:
-- edges and nodes are written in the same transaction, and a stale edge is
-- recoverable while a failed insert mid-ingest is not.

-- Canonical entities gain a link back to the graph so a resolved identity
-- and its node stay associated across restarts.
ALTER TABLE entity_canonical
    ADD COLUMN IF NOT EXISTS graph_node_id text;
CREATE INDEX IF NOT EXISTS entity_canonical_node ON entity_canonical (graph_node_id);

-- Review items need a stable per-document key so a re-ingest updates the
-- open item instead of stacking duplicates in the reviewer's queue.
CREATE UNIQUE INDEX IF NOT EXISTS review_items_open_unique
    ON review_items (doc_id) WHERE resolved_at IS NULL;
