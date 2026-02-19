"""Dynamic Form Engine — banks, forms, sections, fields, submissions, submission_data

Revision ID: 002
Revises: 001
Create Date: 2026-02-19 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── banks ────────────────────────────────────────────────────────────────
    op.create_table(
        'banks',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('code', sa.String(length=20), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code', name='uq_banks_code'),
    )
    op.create_index('ix_banks_id', 'banks', ['id'], unique=False)
    op.create_index('ix_banks_code', 'banks', ['code'], unique=True)

    # ── forms ─────────────────────────────────────────────────────────────────
    op.create_table(
        'forms',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('bank_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['bank_id'], ['banks.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('bank_id', 'code', name='uq_form_bank_code'),
    )
    op.create_index('ix_forms_id', 'forms', ['id'], unique=False)
    op.create_index('ix_forms_bank_id', 'forms', ['bank_id'], unique=False)

    # ── form_sections ─────────────────────────────────────────────────────────
    op.create_table(
        'form_sections',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('form_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.ForeignKeyConstraint(['form_id'], ['forms.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_form_sections_id', 'form_sections', ['id'], unique=False)
    op.create_index('ix_form_sections_form_id', 'form_sections', ['form_id'], unique=False)

    # ── form_fields ───────────────────────────────────────────────────────────
    op.create_table(
        'form_fields',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('form_id', sa.Integer(), nullable=False),
        sa.Column('section_id', sa.Integer(), nullable=True),
        sa.Column('field_key', sa.String(length=100), nullable=False),
        sa.Column('label', sa.String(length=300), nullable=False),
        sa.Column('field_type', sa.String(length=20), nullable=False),
        sa.Column('required', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('validation_rule', sa.JSON(), nullable=True),
        sa.Column('options', sa.JSON(), nullable=True),
        sa.Column('order_index', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.ForeignKeyConstraint(['form_id'], ['forms.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['section_id'], ['form_sections.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('form_id', 'field_key', name='uq_field_form_key'),
    )
    op.create_index('ix_form_fields_id', 'form_fields', ['id'], unique=False)
    op.create_index('ix_form_fields_form_id', 'form_fields', ['form_id'], unique=False)
    op.create_index('ix_form_fields_section_id', 'form_fields', ['section_id'], unique=False)

    # ── submissions ───────────────────────────────────────────────────────────
    op.create_table(
        'submissions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('form_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('current_field_index', sa.Integer(), nullable=False, server_default=sa.text('0')),
        # Voice agent state machine — backend is sole authority over transitions
        sa.Column(
            'conversation_state',
            sa.String(length=30),
            nullable=False,
            server_default='filling_form',
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['form_id'], ['forms.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_submissions_id', 'submissions', ['id'], unique=False)
    op.create_index('ix_submissions_user_id', 'submissions', ['user_id'], unique=False)
    op.create_index('ix_submissions_form_id', 'submissions', ['form_id'], unique=False)


    # ── submission_data ───────────────────────────────────────────────────────
    op.create_table(
        'submission_data',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('submission_id', sa.Integer(), nullable=False),
        sa.Column('field_key', sa.String(length=100), nullable=False),
        sa.Column('value', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['submission_id'], ['submissions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('submission_id', 'field_key', name='uq_submission_field'),
    )
    op.create_index('ix_submission_data_id', 'submission_data', ['id'], unique=False)
    op.create_index('ix_submission_data_submission_id', 'submission_data', ['submission_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_submission_data_submission_id', table_name='submission_data')
    op.drop_index('ix_submission_data_id', table_name='submission_data')
    op.drop_table('submission_data')

    op.drop_index('ix_submissions_form_id', table_name='submissions')
    op.drop_index('ix_submissions_user_id', table_name='submissions')
    op.drop_index('ix_submissions_id', table_name='submissions')
    op.drop_table('submissions')

    op.drop_index('ix_form_fields_section_id', table_name='form_fields')
    op.drop_index('ix_form_fields_form_id', table_name='form_fields')
    op.drop_index('ix_form_fields_id', table_name='form_fields')
    op.drop_table('form_fields')

    op.drop_index('ix_form_sections_form_id', table_name='form_sections')
    op.drop_index('ix_form_sections_id', table_name='form_sections')
    op.drop_table('form_sections')

    op.drop_index('ix_forms_bank_id', table_name='forms')
    op.drop_index('ix_forms_id', table_name='forms')
    op.drop_table('forms')

    op.drop_index('ix_banks_code', table_name='banks')
    op.drop_index('ix_banks_id', table_name='banks')
    op.drop_table('banks')
