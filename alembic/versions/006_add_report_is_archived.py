"""Add is_archived to Report

Revision ID: 006
Revises: 005
Create Date: 2026-03-30 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('reports', sa.Column('is_archived', sa.Boolean(), nullable=True, server_default='false', index=True))


def downgrade() -> None:
    op.drop_column('reports', 'is_archived')
