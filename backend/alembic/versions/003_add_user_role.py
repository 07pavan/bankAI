"""Add role column to users table

Revision ID: 003
Revises: 002
Create Date: 2026-03-08

Adds a non-breaking role column with server default 'user'.
All existing rows automatically receive role='user'.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(length=20),
            nullable=False,
            server_default="user",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "role")
