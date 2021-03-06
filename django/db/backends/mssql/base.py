import datetime
import struct

import pyodbc as Database

from django.db.backends.base.base import BaseDatabaseWrapper
from django.db import DatabaseError

from .client import DatabaseClient
from .creation import DatabaseCreation
from .features import DatabaseFeatures
from .introspection import DatabaseIntrospection
from .operations import DatabaseOperations
from .schema import DatabaseSchemaEditor


def _format_result_row(row):
    return tuple(row)


class ResultSetWrapper:

    def __init__(self, results):
        self.results = results

    def fetchone(self):
        results = self.results.fetchone()

        return _format_result_row(results) if results else results

    def fetchall(self):
        results = self.results.fetchall()

        return list(map(_format_result_row, results))  if results else results

    def fetchmany(self, *args):
        results = self.results.fetchmany(*args)

        return list(map(_format_result_row, results))  if results else results

    def __getattr__(self, attr):
        return getattr(self.results, attr)


class CursorWrapper:
    def __init__(self, cursor):
        self.cursor = cursor
        self.alive = True

    def _format_sql(self, query, args):
        # PyODBC uses ? instead of %s for parameter placeholders
        placeholders = (('?',) * len(args)) if args else tuple()

        if placeholders:
            return query % placeholders
        return query.replace('%%', '%')

    def execute(self, query, args=None):
        if not query:
            return

        args = tuple(args) if args else tuple()
        query = self._format_sql(query, args)

        if args:
            return ResultSetWrapper(self.cursor.execute(query, args))
        else:
            return ResultSetWrapper(self.cursor.execute(query))

    def executemany(self, query, args):
        if not (args and query):
            return

        args = list(args)
        return ResultSetWrapper(self.cursor.executemany(self._format_sql(query, args[0]), args))

    def close(self):
        if self.alive:
            self.alive = False
            self.cursor.close()

    def fetchone(self):
        results = self.cursor.fetchone()
        return _format_result_row(results) if results else results

    def fetchall(self):
        results = self.cursor.fetchall()

        return list(map(_format_result_row, results)) if results else results

    def fetchmany(self, *args):
        results = self.cursor.fetchmany(*args)

        return list(map(_format_result_row, results))  if results else results

    def __getattr__(self, attr):
        return getattr(self.cursor, attr)

    def __iter__(self):
        return iter(self.cursor)


class DatabaseWrapper(BaseDatabaseWrapper):
    vendor = 'mssql'
    display_name = 'MS SQL Server'

    Database = Database
    SchemaEditorClass = DatabaseSchemaEditor

    client_class = DatabaseClient
    creation_class = DatabaseCreation
    features_class = DatabaseFeatures
    introspection_class = DatabaseIntrospection
    ops_class = DatabaseOperations

    data_types = {
        'AutoField': 'int identity(1,1)',
        'BigAutoField': 'bigint identity(1,1)',
        'BinaryField': 'varbinary(MAX)',
        'BooleanField': 'bit',
        'CharField': 'nvarchar(%(max_length)s)',
        'DateField': 'date',
        'DateTimeField': 'datetime2',
        'DecimalField': 'decimal(%(max_digits)s, %(decimal_places)s)',
        'DurationField': 'bigint',
        'FileField': 'nvarchar(%(max_length)s)',
        'FilePathField': 'nvarchar(%(max_length)s)',
        'FloatField': 'real',
        'IntegerField': 'int',
        'BigIntegerField': 'bigint',
        'GenericIPAddressField': 'varchar(39)',
        'NullBooleanField': 'bit',
        'OneToOneField': 'int',
        'PositiveBigIntegerField': 'bigint',
        'PositiveIntegerField': 'int',
        'PositiveSmallIntegerField': 'smallint',
        'SlugField': 'nvarchar(%(max_length)s)',
        'SmallAutoField': 'smallint identity(1,1)',
        'SmallIntegerField': 'smallint',
        'TextField': 'nvarchar(max)',
        'TimeField': 'time',
        'UUIDField': 'char(32)',
    }

    operators = {
        'exact': '= %s',
        'iexact': '= UPPER(%s)',
        'contains': 'LIKE %s',
        'icontains': 'LIKE UPPER(%s)',
        'regex': 'LIKE %s', # SQL Server does not support regex
        'iregex': 'LIKE UPPER(%s)',
        'gt': '> %s',
        'gte': '>= %s',
        'lt': '< %s',
        'lte': '<= %s',
        'startswith': 'LIKE %s',
        'endswith': 'LIKE %s',
        'istartswith': 'LIKE UPPER(%s)',
        'iendswith': 'LIKE UPPER(%s)',
    }

    pattern_esc = r"REPLACE(REPLACE(REPLACE({}, '\', '\\'), '%%', '\%%'), '_', '\_')"
    pattern_ops = {
        'contains': r"LIKE '%%' + {} + '%%' ESCAPE '\'",
        'icontains': r"LIKE '%%' + UPPER({}) + '%%' ESCAPE '\'",
        'startswith': r"LIKE {} + '%%' ESCAPE '\'",
        'istartswith': r"LIKE UPPER({}) + '%%' ESCAPE '\'",
        'endswith': r"LIKE '%%' + {} ESCAPE '\'",
        'iendswith': r"LIKE '%%' + UPPER({}) ESCAPE '\'",
    }

    def get_connection_params(self):
        kwargs = {
            'DRIVER': '{ODBC Driver 17 for SQL Server}'''
        }
        settings_dict = self.settings_dict

        if settings_dict['USER']:
            kwargs['Uid'] = settings_dict['USER']

        if settings_dict['NAME']:
            kwargs['Database'] = settings_dict['NAME']

        if settings_dict['PASSWORD']:
            kwargs['Pwd'] = settings_dict['PASSWORD']

        if settings_dict['HOST']:
            kwargs['Server'] = settings_dict['HOST']

        return kwargs

    def get_new_connection(self, conn_params):
        connection_string = ';'.join('{}={}'.format(k, v) for (k, v) in conn_params.items())

        try:
            connection = Database.connect(connection_string)
        except Database.InterfaceError as e:
            if e.args[0] in ('28000',):
                raise DatabaseError('Could not connect to the database') from e
        except:
            raise

        return connection

    def init_connection_state(self):
        set_options = ('LANGUAGE', 'DATEFIRST')
        for option in set_options:
            if option in self.settings_dict['OPTIONS']:
                value = self.settings_dict['OPTIONS'].get(option)
                self.connection.execute('SET {0} {1}'.format(option, value))

    def create_cursor(self, name=None):
        return CursorWrapper(self.connection.cursor())

    def _set_autocommit(self, autocommit):
        self.connection.autocommit = autocommit

    def is_usable(self):
        try:
            self.connection.execute("SELECT 1").fetchall()
        except Database.Error:
            return False

        return True
