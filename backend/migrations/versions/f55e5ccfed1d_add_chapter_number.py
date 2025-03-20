"""add chapter number

Revision ID: f55e5ccfed1d
Revises: 9491914a5675
Create Date: 2025-03-20 14:03:54.884670

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '9491914a5675'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Check if chapter_number column exists
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = [column['name'] for column in inspector.get_columns('chapters')]

    # If chapter_number doesn't exist (which we now know it does), add it
    if 'chapter_number' not in columns:
        op.add_column('chapters', 
                    sa.Column('chapter_number', sa.Integer(), nullable=True))

        # Update existing rows with sequential chapter numbers
        op.execute("""
            WITH numbered_chapters AS (
                SELECT id, novel_id, ROW_NUMBER() OVER(PARTITION BY novel_id ORDER BY id) as row_num
                FROM chapters
            )
            UPDATE chapters
            SET chapter_number = numbered_chapters.row_num
            FROM numbered_chapters
            WHERE chapters.id = numbered_chapters.id
        """)

        # Make the column non-nullable after populating it
        op.alter_column('chapters', 'chapter_number', nullable=False)
    else:
        # If the column exists but is nullable, make it non-nullable
        column_info = next((c for c in inspector.get_columns('chapters') if c['name'] == 'chapter_number'), None)
        if column_info and column_info.get('nullable', False):
            # Check if there are any NULL values
            result = connection.execute(sa.text("SELECT COUNT(*) FROM chapters WHERE chapter_number IS NULL")).scalar()

            if result > 0:
                # Populate NULL values with sequential numbers
                op.execute("""
                    WITH numbered_chapters AS (
                        SELECT id, novel_id, ROW_NUMBER() OVER(PARTITION BY novel_id ORDER BY id) as row_num
                        FROM chapters
                        WHERE chapter_number IS NULL
                    )
                    UPDATE chapters
                    SET chapter_number = numbered_chapters.row_num
                    FROM numbered_chapters
                    WHERE chapters.id = numbered_chapters.id
                """)

            # Make the column non-nullable
            op.alter_column('chapters', 'chapter_number', nullable=False)

    # Check if the unique constraint already exists
    constraints = inspector.get_unique_constraints('chapters')
    constraint_exists = any(
        'novel_id' in constraint['column_names'] and 
        'chapter_number' in constraint['column_names'] 
        for constraint in constraints
    )

    # Add unique constraint if it doesn't exist
    if not constraint_exists:
        op.create_unique_constraint('uix_chapter_novel_number', 'chapters', ['novel_id', 'chapter_number'])


def downgrade() -> None:
    """Downgrade schema."""
    # Drop unique constraint
    try:
        op.drop_constraint('uix_chapter_novel_number', 'chapters', type_='unique')
    except Exception:
        # Constraint might not exist if upgrade was partial
        pass


