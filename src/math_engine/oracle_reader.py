"""Optional SELECT-only source reader. Never updates Oracle or commits a transaction."""
import json
import os
from pathlib import Path
import re
from .contracts import Contract, Dataset


def quote(name):
    parts = name.split('.')
    if not 1 <= len(parts) <= 2 or any(not re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}', part) for part in parts):
        raise ValueError('Use uppercase allowlisted Oracle identifiers')
    return '.'.join('"' + part + '"' for part in parts)


class ReadProfile(Contract):
    table: str
    id_column: str = 'ID'
    scenario_column: str = 'SCENARIO_CODE'
    inputs: list[str]

    def check(self):
        quote(self.table)
        names = [self.id_column, self.scenario_column] + self.inputs
        if len(names) != len(set(names)) or not self.inputs:
            raise ValueError('Profile columns must be distinct with nonempty inputs')
        for name in names:
            if '.' in name:
                raise ValueError('Columns cannot be qualified')
            quote(name)


class OracleReader:
    def __init__(self, profiles, connect):
        self.profiles, self.connect = profiles, connect
        for profile in profiles.values():
            profile.check()

    @classmethod
    def from_environment(cls):
        path = os.environ.get('ORACLE_READ_PROFILES_FILE')
        if not path:
            return None
        content = json.loads(Path(path).read_text(encoding='utf-8'))
        profiles = {name: ReadProfile.model_validate(value) for name, value in content['profiles'].items()}

        def connect():
            import oracledb
            return oracledb.connect(user=os.environ['ORACLE_USER'], password=os.environ['ORACLE_PASSWORD'], dsn=os.environ['ORACLE_DSN'])
        return cls(profiles, connect)

    def read(self, profile_name, scenario_code):
        if not scenario_code.strip():
            raise ValueError('An explicit nonempty scenario_code is required')
        profile = self.profiles[profile_name]
        columns = [profile.id_column] + profile.inputs
        sql = (f"SELECT {', '.join(map(quote, columns))} FROM {quote(profile.table)} "
               f"WHERE {quote(profile.scenario_column)} = :scenario ORDER BY {quote(profile.id_column)}")
        conn = self.connect()
        cur = conn.cursor()
        try:
            cur.execute(sql, {'scenario': scenario_code.strip()})
            records = cur.fetchmany(10001)
            if not records or len(records) > 10000 or any(row[0] is None for row in records):
                raise ValueError('Source must contain 1..10000 rows with non-null IDs')
            dataset = Dataset(row_ids=[str(row[0]) for row in records],
                              rows=[dict(zip(profile.inputs, row[1:])) for row in records])
            return dataset, {'type': 'oracle_read', 'profile': profile_name, 'scenario_code': scenario_code.strip()}
        finally:
            cur.close()
            conn.close()
