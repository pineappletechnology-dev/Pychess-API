"""table users

Revision ID: 4f376b0c87d0
Revises: 45b1080e6ebd
Create Date: 2025-02-19 13:57:17.373625

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4f376b0c87d0'
down_revision: Union[str, None] = '45b1080e6ebd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('username', sa.String(50), nullable=False),
        sa.Column('password', sa.String(50), nullable=False),
        sa.Column('wins', sa.Integer),
        sa.Column('losses', sa.Integer),
        sa.Column('total_games', sa.Integer),
    )


def downgrade() -> None:
    pass
