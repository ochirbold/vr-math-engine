from decimal import Decimal
import pytest
from math_engine.oracle_reader import OracleReader, ReadProfile
from math_engine.storage import DataStore


class Cursor:
    def __init__(self, rows):
        self.rows, self.calls, self.closed = rows, [], False

    def execute(self, sql, params):
        assert sql.startswith('SELECT ')
        self.calls.append((sql, params))

    def fetchmany(self, count):
        assert count == 10001
        return self.rows[:count]

    def close(self):
        self.closed = True


class Connection:
    def __init__(self, cursor):
        self.cur, self.closed = cursor, False

    def cursor(self):
        return self.cur

    def close(self):
        self.closed = True

    def commit(self):
        raise AssertionError('Reader must never commit')


def test_read_only_bind_and_snapshot(tmp_path):
    cursor = Cursor([(Decimal('101'), Decimal('2')), (Decimal('102'), Decimal('3'))])
    conn = Connection(cursor)
    reader = OracleReader({'test': ReadProfile(table='TEST_OWNER.DATA', inputs=['QTY'])}, lambda: conn)
    scenario = "test' OR 1=1 --"
    dataset, origin = reader.read('test', scenario)
    sql, params = cursor.calls[0]
    assert scenario not in sql and params == {'scenario': scenario}
    assert dataset.rows == [{'QTY': 2}, {'QTY': 3}]
    assert dataset.row_ids == ['101', '102']
    assert conn.closed and cursor.closed
    store = DataStore(tmp_path / 'data.db')
    snapshot = store.snapshot(dataset, origin)['snapshot_id']
    assert store.read(snapshot) == dataset.model_dump()
    assert store.envelope(snapshot)['origin'] == origin


def test_profile_and_scope_validation():
    with pytest.raises(ValueError):
        OracleReader({'bad': ReadProfile(table='DATA; DELETE', inputs=['X'])}, lambda: None)
    reader = OracleReader({'test': ReadProfile(table='DATA', inputs=['X'])}, lambda: None)
    with pytest.raises(ValueError):
        reader.read('test', '  ')
    with pytest.raises(KeyError):
        reader.read('unknown', 'test')


def test_reader_closes_on_bad_data():
    cursor = Cursor([(None, 1)])
    conn = Connection(cursor)
    reader = OracleReader({'test': ReadProfile(table='DATA', inputs=['X'])}, lambda: conn)
    with pytest.raises(ValueError):
        reader.read('test', 'test')
    assert cursor.closed and conn.closed
