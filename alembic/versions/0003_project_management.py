"""project folders and session project binding

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-12
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _columns(bind, table: str) -> set[str]:
    rows = bind.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def upgrade() -> None:
    bind = op.get_bind()
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id VARCHAR(64) NOT NULL,
            user_id VARCHAR(64) NOT NULL,
            name VARCHAR(128) NOT NULL,
            path VARCHAR(1024) NOT NULL,
            status VARCHAR(32) NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            UNIQUE (path)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_projects_user_id ON projects (user_id)")
    if "project_id" not in _columns(bind, "sessions"):
        op.execute("ALTER TABLE sessions ADD COLUMN project_id VARCHAR(64)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sessions_project_id ON sessions (project_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_sessions_project_id")
    op.execute("ALTER TABLE sessions DROP COLUMN project_id")
    op.execute("DROP TABLE IF EXISTS projects")
