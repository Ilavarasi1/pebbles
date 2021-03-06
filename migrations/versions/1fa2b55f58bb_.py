"""Add namespaced keyvalues.

Revision ID: 1fa2b55f58bb
Revises: 5b9110dd4ffd
Create Date: 2017-04-05 13:26:24.777459

"""

# revision identifiers, used by Alembic.
revision = '1fa2b55f58bb'
down_revision = '5b9110dd4ffd'

from alembic import op
import sqlalchemy as sa


def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.create_table('namespaced_keyvalues',
    sa.Column('namespace', sa.String(length=32), nullable=False),
    sa.Column('key', sa.String(length=128), nullable=False),
    sa.Column('_value', sa.Text(), nullable=True),
    sa.Column('created_ts', sa.Float(), nullable=True),
    sa.Column('updated_ts', sa.Float(), nullable=True),
    sa.PrimaryKeyConstraint('namespace', 'key', name=op.f('pk_namespaced_keyvalues'))
    )
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('namespaced_keyvalues')
    ### end Alembic commands ###
