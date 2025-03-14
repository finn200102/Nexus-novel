# 1. Update your SQLAlchemy model
# 2. Generate a migration
alembic revision --autogenerate -m "Description of change"
# 3. Review the generated migration file
# 4. Apply the migration
alembic upgrade head

