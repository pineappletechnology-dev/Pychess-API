"""table games

Revision ID: 677425982a5a
Revises: 5eeba38760fe
Create Date: 2025-02-19 14:29:39.338981

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '677425982a5a'
down_revision: Union[str, None] = '5eeba38760fe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'games',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id', ondelete='CASCADE')),
        sa.Column('player_win', sa.Boolean)
    )
    pass


def downgrade() -> None:
    pass
