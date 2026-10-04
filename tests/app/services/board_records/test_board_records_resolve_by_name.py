import threading

import pytest

from invokeai.app.services.board_records.board_records_common import (
    BoardChanges,
    BoardRecordNameAmbiguousException,
    BoardVisibility,
)
from invokeai.app.services.board_records.board_records_sqlite import SqliteBoardRecordStorage
from invokeai.app.services.config.config_default import InvokeAIAppConfig
from invokeai.app.services.project_records.project_records_sqlite import ProjectRecordsSqlite
from invokeai.app.services.shared.sqlite.sqlite_database import SqliteDatabase
from invokeai.backend.util.logging import InvokeAILogger
from tests.fixtures.sqlite_database import create_mock_sqlite_database

USER = "system"
OTHER_USER = "someone-else"


@pytest.fixture
def db() -> SqliteDatabase:
    config = InvokeAIAppConfig(use_memory_db=True)
    return create_mock_sqlite_database(config=config, logger=InvokeAILogger.get_logger())


@pytest.fixture
def storage(db: SqliteDatabase) -> SqliteBoardRecordStorage:
    return SqliteBoardRecordStorage(db=db)


def _count_boards(db: SqliteDatabase, board_name: str) -> int:
    with db.transaction() as cursor:
        cursor.execute("SELECT COUNT(*) FROM boards WHERE board_name = ?", (board_name,))
        return cursor.fetchone()[0]


def test_finds_existing_own_board(storage: SqliteBoardRecordStorage) -> None:
    existing = storage.save("toyrobot-lo", USER)

    result = storage.resolve_by_name(USER, "toyrobot-lo", create_if_missing=False)

    assert result is not None
    assert result.board_id == existing.board_id


def test_returns_none_without_writing_when_missing_and_not_creating(
    storage: SqliteBoardRecordStorage, db: SqliteDatabase
) -> None:
    assert storage.resolve_by_name(USER, "toyrobot-lo", create_if_missing=False) is None
    assert _count_boards(db, "toyrobot-lo") == 0


def test_creates_when_missing_and_second_call_finds_the_same_board(storage: SqliteBoardRecordStorage) -> None:
    created = storage.resolve_by_name(USER, "toyrobot-lo", create_if_missing=True)
    again = storage.resolve_by_name(USER, "toyrobot-lo", create_if_missing=True)

    assert created is not None and again is not None
    assert again.board_id == created.board_id


def test_created_board_is_an_ordinary_private_board_of_the_user(storage: SqliteBoardRecordStorage) -> None:
    created = storage.resolve_by_name(USER, "toyrobot-lo", create_if_missing=True)

    assert created is not None
    assert created.board_name == "toyrobot-lo"
    assert created.user_id == USER
    assert created.archived is False
    assert created.board_visibility == BoardVisibility.Private
    assert storage.get_project_ids_for_boards([created.board_id]) == {}


def test_duplicates_raise_naming_every_matching_board(storage: SqliteBoardRecordStorage) -> None:
    first = storage.save("toyrobot-lo", USER)
    second = storage.save("toyrobot-lo", USER)

    with pytest.raises(BoardRecordNameAmbiguousException) as exc_info:
        storage.resolve_by_name(USER, "toyrobot-lo", create_if_missing=True)

    assert set(exc_info.value.board_ids) == {first.board_id, second.board_id}
    assert exc_info.value.board_name == "toyrobot-lo"
    message = str(exc_info.value)
    assert message.startswith('Multiple boards named "toyrobot-lo" (ids: ')
    assert message.endswith("). Rename or archive all but one.")
    assert first.board_id in message and second.board_id in message


def test_ignores_another_users_board(storage: SqliteBoardRecordStorage) -> None:
    theirs = storage.save("toyrobot-lo", OTHER_USER)
    storage.update(theirs.board_id, BoardChanges(board_visibility=BoardVisibility.Public))

    assert storage.resolve_by_name(USER, "toyrobot-lo", create_if_missing=False) is None
    created = storage.resolve_by_name(USER, "toyrobot-lo", create_if_missing=True)

    assert created is not None
    assert created.board_id != theirs.board_id
    assert created.user_id == USER


def test_own_board_wins_over_another_users_board_with_the_same_name(storage: SqliteBoardRecordStorage) -> None:
    storage.save("toyrobot-lo", OTHER_USER)
    mine = storage.save("toyrobot-lo", USER)

    result = storage.resolve_by_name(USER, "toyrobot-lo", create_if_missing=False)

    assert result is not None
    assert result.board_id == mine.board_id


def test_ignores_archived_board(storage: SqliteBoardRecordStorage) -> None:
    archived = storage.save("toyrobot-lo", USER)
    storage.update(archived.board_id, BoardChanges(archived=True))

    assert storage.resolve_by_name(USER, "toyrobot-lo", create_if_missing=False) is None
    created = storage.resolve_by_name(USER, "toyrobot-lo", create_if_missing=True)

    assert created is not None
    assert created.board_id != archived.board_id


def test_archived_duplicate_does_not_make_the_active_board_ambiguous(storage: SqliteBoardRecordStorage) -> None:
    archived = storage.save("toyrobot-lo", USER)
    storage.update(archived.board_id, BoardChanges(archived=True))
    active = storage.save("toyrobot-lo", USER)

    result = storage.resolve_by_name(USER, "toyrobot-lo", create_if_missing=False)

    assert result is not None
    assert result.board_id == active.board_id


def test_ignores_project_board(storage: SqliteBoardRecordStorage, db: SqliteDatabase) -> None:
    projects = ProjectRecordsSqlite(db=db)
    project = projects.create(USER, "Robot Streets", {})
    project_board_id = projects.get_board_id(USER, project.project_id)
    project_board_name = storage.get(project_board_id).board_name

    assert storage.resolve_by_name(USER, project_board_name, create_if_missing=False) is None
    created = storage.resolve_by_name(USER, project_board_name, create_if_missing=True)

    assert created is not None
    assert created.board_id != project_board_id
    assert storage.get_project_ids_for_boards([created.board_id]) == {}


def test_matching_is_exact_and_case_sensitive(storage: SqliteBoardRecordStorage) -> None:
    storage.save("ToyRobot-lo", USER)

    assert storage.resolve_by_name(USER, "toyrobot-lo", create_if_missing=False) is None
    assert storage.resolve_by_name(USER, "toyrobot", create_if_missing=False) is None


def test_concurrent_creates_produce_exactly_one_board(storage: SqliteBoardRecordStorage, db: SqliteDatabase) -> None:
    workers = 8
    barrier = threading.Barrier(workers)
    results: list[str] = []
    errors: list[BaseException] = []

    def resolve() -> None:
        try:
            barrier.wait()
            record = storage.resolve_by_name(USER, "toyrobot-lo", create_if_missing=True)
            assert record is not None
            results.append(record.board_id)
        except BaseException as e:  # collected and re-raised on the main thread
            errors.append(e)

    threads = [threading.Thread(target=resolve) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(results) == workers
    assert len(set(results)) == 1
    assert _count_boards(db, "toyrobot-lo") == 1
