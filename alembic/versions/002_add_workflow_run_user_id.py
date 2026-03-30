"""Add user_id column to workflow_runs table

Revision ID: 002_add_workflow_run_user_id
Revises: 001_initial
Create Date: 2026-03-29
"""
from alembic import op
import sqlalchemy as sa

revision = '002_add_workflow_run_user_id'
down_revision = '001_initial'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('workflow_runs', sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True))
    op.create_index('idx_workflow_runs_user_id', 'workflow_runs', ['user_id'])


def downgrade():
    op.drop_index('idx_workflow_runs_user_id', 'workflow_runs')
    op.drop_column('workflow_runs', 'user_id')
