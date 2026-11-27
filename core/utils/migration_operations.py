"""
Operações de migração idempotentes no banco de dados.

O estado (state) das migrações é o mesmo das operações do Django; somente a
execução no banco verifica antes se a coluna, o índice ou a constraint já
existe. Servem para que a mesma migração funcione em bancos que aplicaram
versões anteriores de migrações de um branch (ex.: bancos de
desenvolvimento) e em bancos que nunca as aplicaram (ex.: produção).

Não importar modelos neste módulo: ele é usado pelas migrações.
"""

from django.db import migrations


def table_columns(schema_editor, table):
    with schema_editor.connection.cursor() as cursor:
        return {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(
                cursor, table
            )
        }


def table_constraints(schema_editor, table):
    """Constraints e índices da tabela: {nome: info}"""
    with schema_editor.connection.cursor() as cursor:
        return schema_editor.connection.introspection.get_constraints(cursor, table)


class AddFieldIfNotExists(migrations.AddField):
    """AddField que não altera o banco se a coluna já existe"""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        field = model._meta.get_field(self.name)
        if field.column in table_columns(schema_editor, model._meta.db_table):
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)


class AddIndexIfNotExists(migrations.AddIndex):
    """AddIndex que não altera o banco se o índice já existe"""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        if self.index.name in table_constraints(schema_editor, model._meta.db_table):
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)


class AddConstraintIfNotExists(migrations.AddConstraint):
    """AddConstraint que não altera o banco se a constraint já existe"""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        if self.constraint.name in table_constraints(
            schema_editor, model._meta.db_table
        ):
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)


class AlterFieldRemoveUniqueIfExists(migrations.AlterField):
    """
    AlterField que remove unique=True do campo somente se o banco ainda tem
    a constraint única do campo (desconsidera os índices únicos e as
    constraints declaradas em Meta, ex.: UniqueConstraint condicional)
    """

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        from_model = from_state.apps.get_model(app_label, self.model_name)
        to_model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, to_model):
            return
        column = from_model._meta.get_field(self.name).column
        meta_names = {
            item.name
            for item in list(to_model._meta.constraints) + list(to_model._meta.indexes)
        }
        # unique=True gera constraint (index=False); UniqueConstraint
        # condicional gera índice único (index=True)
        has_unique = any(
            info["unique"]
            and not info["primary_key"]
            and not info["index"]
            and info["columns"] == [column]
            and name not in meta_names
            for name, info in table_constraints(
                schema_editor, from_model._meta.db_table
            ).items()
        )
        if not has_unique:
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)


def ensure_fields_and_indexes(app_label, model_name, field_names=(), index_names=()):
    """
    Recria no banco, se ausentes, colunas e índices que já fazem parte do
    estado das migrações (ex.: removidos por versão anterior de uma migração
    de branch, já descartada). Não altera o estado.
    """

    def forwards(apps, schema_editor):
        model = apps.get_model(app_label, model_name)
        table = model._meta.db_table
        columns = table_columns(schema_editor, table)
        for name in field_names:
            field = model._meta.get_field(name)
            if field.column not in columns:
                schema_editor.add_field(model, field)
        existing = table_constraints(schema_editor, table)
        for index in model._meta.indexes:
            if index.name in index_names and index.name not in existing:
                schema_editor.add_index(model, index)

    return migrations.RunPython(forwards, migrations.RunPython.noop, elidable=True)
