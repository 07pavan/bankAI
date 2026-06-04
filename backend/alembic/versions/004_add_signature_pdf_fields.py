"""Add signature and PDF fields to submissions

Revision ID: 004
Revises: 003
Create Date: 2026-04-21 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add signature capture path
    op.add_column(
        'submissions',
        sa.Column('signature_path', sa.String(length=500), nullable=True),
    )
    # Add generated PDF path
    op.add_column(
        'submissions',
        sa.Column('pdf_path', sa.String(length=500), nullable=True),
    )
    # Add timestamp for when signature was captured
    op.add_column(
        'submissions',
        sa.Column('signed_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('submissions', 'signed_at')
    op.drop_column('submissions', 'pdf_path')
    op.drop_column('submissions', 'signature_path')
