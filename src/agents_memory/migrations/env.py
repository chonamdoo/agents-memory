from alembic import context

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Run migrations.migrate with an explicit operator DSN")
context.configure(connection=connection, transaction_per_migration=True)
with context.begin_transaction():
    context.run_migrations()
