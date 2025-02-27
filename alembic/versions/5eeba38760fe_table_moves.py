"""table moves

Revision ID: 5eeba38760fe
Revises: 4f376b0c87d0
Create Date: 2025-02-19 14:17:03.646458

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5eeba38760fe'
down_revision: Union[str, None] = '4f376b0c87d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'moves',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('is_player', sa.Boolean),
        sa.Column('move', sa.String(4)),
        sa.Column('mv_quality', sa.String(10)),
        sa.Column('game_id', sa.Integer, sa.ForeignKey('game.id', ondelete='CASCADE')),

    )
    pass


def downgrade() -> None:
    pass
