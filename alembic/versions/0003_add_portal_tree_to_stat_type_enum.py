"""add_portal_tree_to_stat_type_enum

Revision ID: 0003
Revises: 
Create Date: 1970-01-01 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute("""
alter type stat_type
    add value 'portal-tree' before 'search';
""")


def downgrade():
    conn = op.get_bind()
    conn.execute("""
delete from stats
    where stat_type = 'portal-tree'::stat_type;
 
alter type stat_type
    rename to stat_type_old;

    
create type stat_type as enum
(
    'search',
    'material-types',
    'validation-collections',
    'validation-materials'
);

alter table stats
    alter column stat_type type stat_type using stat_type::text::stat_type;

drop type stat_type_old;
""")
