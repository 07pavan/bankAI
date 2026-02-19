"""Initial migration - Users and KYC submissions with encryption

Revision ID: 001
Revises: 
Create Date: 2026-02-16 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('aadhaar_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_aadhaar_hash'), 'users', ['aadhaar_hash'], unique=True)
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)

    # Create kyc_submissions table
    op.create_table(
        'kyc_submissions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('aadhaar_encrypted', sa.Text(), nullable=False),
        sa.Column('pan_encrypted', sa.Text(), nullable=False),
        sa.Column('aadhaar_hash', sa.String(length=64), nullable=False),
        sa.Column('selfie_path', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_kyc_submissions_aadhaar_hash'), 'kyc_submissions', ['aadhaar_hash'], unique=False)
    op.create_index(op.f('ix_kyc_submissions_id'), 'kyc_submissions', ['id'], unique=False)
    op.create_index('idx_user_status', 'kyc_submissions', ['user_id', 'status'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_user_status', table_name='kyc_submissions')
    op.drop_index(op.f('ix_kyc_submissions_id'), table_name='kyc_submissions')
    op.drop_index(op.f('ix_kyc_submissions_aadhaar_hash'), table_name='kyc_submissions')
    op.drop_table('kyc_submissions')
    op.drop_index(op.f('ix_users_id'), table_name='users')
    op.drop_index(op.f('ix_users_aadhaar_hash'), table_name='users')
    op.drop_table('users')
