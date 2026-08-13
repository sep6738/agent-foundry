"""complete runtime tables, columns, and FTS indexes

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-10
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _columns(bind, table: str) -> set[str]:
    rows = bind.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def upgrade() -> None:
    bind = op.get_bind()

    if "keywords" not in _columns(bind, "memory_facts"):
        op.execute("ALTER TABLE memory_facts ADD COLUMN keywords JSON")
    compression_columns = _columns(bind, "compression_records")
    if "replaced_entry_ids" not in compression_columns:
        op.execute("ALTER TABLE compression_records ADD COLUMN replaced_entry_ids JSON")
    if "kept_window_entries" not in compression_columns:
        op.execute(
            "ALTER TABLE compression_records ADD COLUMN kept_window_entries INTEGER DEFAULT 0"
        )
    if "cache_invalidated" not in compression_columns:
        op.execute("ALTER TABLE compression_records ADD COLUMN cache_invalidated INTEGER DEFAULT 0")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS graph_checkpoints (
            id VARCHAR(64) NOT NULL,
            thread_id VARCHAR(128) NOT NULL,
            checkpoint_ns VARCHAR(128) NOT NULL,
            checkpoint_id VARCHAR(128) NOT NULL,
            parent_checkpoint_id VARCHAR(128),
            type VARCHAR(32) NOT NULL,
            payload BLOB NOT NULL,
            metadata_type VARCHAR(32) NOT NULL,
            metadata_blob BLOB NOT NULL,
            created_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_graph_checkpoint UNIQUE (thread_id, checkpoint_ns, checkpoint_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS graph_checkpoint_writes (
            id VARCHAR(64) NOT NULL,
            thread_id VARCHAR(128) NOT NULL,
            checkpoint_ns VARCHAR(128) NOT NULL,
            checkpoint_id VARCHAR(128) NOT NULL,
            task_id VARCHAR(128) NOT NULL,
            idx INTEGER NOT NULL,
            channel VARCHAR(128) NOT NULL,
            type VARCHAR(32) NOT NULL,
            payload BLOB NOT NULL,
            task_path VARCHAR(256) NOT NULL,
            created_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_graph_checkpoint_write
                UNIQUE (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_graph_checkpoints_thread_id ON graph_checkpoints (thread_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_graph_checkpoints_checkpoint_id "
        "ON graph_checkpoints (checkpoint_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_graph_checkpoint_writes_thread_id "
        "ON graph_checkpoint_writes (thread_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_graph_checkpoint_writes_checkpoint_id "
        "ON graph_checkpoint_writes (checkpoint_id)"
    )

    op.execute("DROP TRIGGER IF EXISTS memory_facts_fts_insert")
    op.execute("DROP TRIGGER IF EXISTS memory_facts_fts_update")
    op.execute("DROP TRIGGER IF EXISTS memory_facts_fts_delete")
    op.execute("DROP TRIGGER IF EXISTS skills_fts_insert")
    op.execute("DROP TRIGGER IF EXISTS skills_fts_update")
    op.execute("DROP TRIGGER IF EXISTS skills_fts_delete")
    op.execute("DROP TABLE IF EXISTS memory_facts_fts")
    op.execute("DROP TABLE IF EXISTS skills_fts")
    op.execute(
        """
        CREATE VIRTUAL TABLE memory_facts_fts
        USING fts5(id UNINDEXED, subject, content, tags, keywords)
        """
    )
    op.execute(
        """
        CREATE VIRTUAL TABLE skills_fts
        USING fts5(id UNINDEXED, name, description, content)
        """
    )
    op.execute(
        """
        INSERT INTO memory_facts_fts(id, subject, content, tags, keywords)
        SELECT id, subject, content, COALESCE(tags, '[]'), COALESCE(keywords, '[]')
        FROM memory_facts
        """
    )
    op.execute(
        """
        INSERT INTO skills_fts(id, name, description, content)
        SELECT id, name, description, ''
        FROM skills
        """
    )
    op.execute(
        """
        CREATE TRIGGER memory_facts_fts_insert AFTER INSERT ON memory_facts
        BEGIN
            INSERT INTO memory_facts_fts(id, subject, content, tags, keywords)
            VALUES (new.id, new.subject, new.content, new.tags, new.keywords);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER memory_facts_fts_update AFTER UPDATE ON memory_facts
        BEGIN
            DELETE FROM memory_facts_fts WHERE id = old.id;
            INSERT INTO memory_facts_fts(id, subject, content, tags, keywords)
            VALUES (new.id, new.subject, new.content, new.tags, new.keywords);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER memory_facts_fts_delete AFTER DELETE ON memory_facts
        BEGIN
            DELETE FROM memory_facts_fts WHERE id = old.id;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER skills_fts_insert AFTER INSERT ON skills
        BEGIN
            INSERT INTO skills_fts(id, name, description, content)
            VALUES (new.id, new.name, new.description, '');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER skills_fts_update AFTER UPDATE ON skills
        BEGIN
            DELETE FROM skills_fts WHERE id = old.id;
            INSERT INTO skills_fts(id, name, description, content)
            VALUES (new.id, new.name, new.description, '');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER skills_fts_delete AFTER DELETE ON skills
        BEGIN
            DELETE FROM skills_fts WHERE id = old.id;
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS memory_facts_fts_insert")
    op.execute("DROP TRIGGER IF EXISTS memory_facts_fts_update")
    op.execute("DROP TRIGGER IF EXISTS memory_facts_fts_delete")
    op.execute("DROP TRIGGER IF EXISTS skills_fts_insert")
    op.execute("DROP TRIGGER IF EXISTS skills_fts_update")
    op.execute("DROP TRIGGER IF EXISTS skills_fts_delete")
    op.execute("DROP TABLE IF EXISTS memory_facts_fts")
    op.execute("DROP TABLE IF EXISTS skills_fts")
    op.execute("DROP TABLE IF EXISTS graph_checkpoint_writes")
    op.execute("DROP TABLE IF EXISTS graph_checkpoints")
    op.execute("ALTER TABLE compression_records DROP COLUMN cache_invalidated")
    op.execute("ALTER TABLE compression_records DROP COLUMN kept_window_entries")
    op.execute("ALTER TABLE compression_records DROP COLUMN replaced_entry_ids")
    op.execute("ALTER TABLE memory_facts DROP COLUMN keywords")
