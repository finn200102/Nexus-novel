"""Immutable row lifecycles for external-export acknowledgements."""
from sqlalchemy import event


def install(connection, table):
    name=table.name if hasattr(table,'name') else table
    if name not in ('reading_annotations','readwise_connections'):raise ValueError(name)
    if connection.dialect.name=='sqlite':
        connection.exec_driver_sql(f'''CREATE TRIGGER IF NOT EXISTS {name}_export_key_insert AFTER INSERT ON {name}
            WHEN NEW.export_key IS NULL BEGIN UPDATE {name} SET export_key=lower(hex(randomblob(16))) WHERE id=NEW.id; END''')
        connection.exec_driver_sql(f'''CREATE TRIGGER IF NOT EXISTS {name}_export_key_immutable BEFORE UPDATE OF export_key ON {name}
            WHEN OLD.export_key IS NOT NULL AND NEW.export_key IS NOT OLD.export_key BEGIN SELECT RAISE(ABORT,'immutable export lifecycle'); END''')
    elif connection.dialect.name=='postgresql':
        connection.exec_driver_sql(f'''CREATE OR REPLACE FUNCTION {name}_export_key_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            IF TG_OP='INSERT' THEN NEW.export_key=coalesce(NEW.export_key,gen_random_uuid()::text);
            ELSIF NEW.export_key IS DISTINCT FROM OLD.export_key THEN RAISE EXCEPTION 'immutable export lifecycle'; END IF; RETURN NEW; END $$''')
        connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS {name}_export_key_guard ON {name}')
        connection.exec_driver_sql(f'CREATE TRIGGER {name}_export_key_guard BEFORE INSERT OR UPDATE OF export_key ON {name} FOR EACH ROW EXECUTE FUNCTION {name}_export_key_fn()')


def register(table):
    event.listen(table,'after_create',lambda target,connection,**kw:install(connection,target))
