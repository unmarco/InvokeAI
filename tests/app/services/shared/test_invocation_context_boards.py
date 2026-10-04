from unittest.mock import MagicMock, create_autospec

import pytest

from invokeai.app.services.board_records.board_records_common import BOARD_NAME_MAX_LENGTH, BoardRecordOrderBy
from invokeai.app.services.boards.boards_base import BoardServiceABC
from invokeai.app.services.shared.invocation_context import BoardsInterface
from invokeai.app.services.shared.sqlite.sqlite_common import SQLiteDirection


def _make_interface(multiuser: bool, user: MagicMock | None) -> tuple[BoardsInterface, MagicMock]:
    services = MagicMock()
    # Autospec so a call that doesn't match the real BoardService signature fails like it does at runtime.
    services.boards = create_autospec(BoardServiceABC, instance=True)
    services.configuration.multiuser = multiuser
    services.users.get.return_value = user
    data = MagicMock()
    data.queue_item.user_id = "queue-user"
    return BoardsInterface(services, data), services


def test_get_all_runs_as_admin_in_single_user_mode() -> None:
    boards, services = _make_interface(multiuser=False, user=None)

    boards.get_all()

    services.boards.get_all.assert_called_once_with(
        "queue-user", True, order_by=BoardRecordOrderBy.CreatedAt, direction=SQLiteDirection.Descending
    )
    services.users.get.assert_not_called()


@pytest.mark.parametrize(
    ("user", "expected_is_admin"),
    [
        (MagicMock(is_admin=True, is_active=True), True),
        (MagicMock(is_admin=False, is_active=True), False),
        (None, False),
    ],
)
def test_get_all_uses_queue_user_role_in_multiuser_mode(user: MagicMock | None, expected_is_admin: bool) -> None:
    boards, services = _make_interface(multiuser=True, user=user)

    boards.get_all()

    services.users.get.assert_called_once_with("queue-user")
    services.boards.get_all.assert_called_once_with(
        "queue-user", expected_is_admin, order_by=BoardRecordOrderBy.CreatedAt, direction=SQLiteDirection.Descending
    )


@pytest.mark.parametrize("is_admin", [True, False])
def test_get_all_rejects_deactivated_queue_user_in_multiuser_mode(is_admin: bool) -> None:
    boards, services = _make_interface(multiuser=True, user=MagicMock(is_admin=is_admin, is_active=False))

    with pytest.raises(PermissionError):
        boards.get_all()

    services.boards.get_all.assert_not_called()


def test_resolve_passes_trimmed_name_and_queue_user_in_single_user_mode() -> None:
    boards, services = _make_interface(multiuser=False, user=None)

    boards.resolve("  toyrobot-lo \n")

    services.boards.resolve_by_name.assert_called_once_with("queue-user", "toyrobot-lo", False)
    services.users.get.assert_not_called()


def test_resolve_keeps_inner_whitespace() -> None:
    boards, services = _make_interface(multiuser=False, user=None)

    boards.resolve("  toy robot  ")

    services.boards.resolve_by_name.assert_called_once_with("queue-user", "toy robot", False)


def test_resolve_passes_create_if_missing_through() -> None:
    boards, services = _make_interface(multiuser=False, user=None)

    boards.resolve("toyrobot-lo", create_if_missing=True)

    services.boards.resolve_by_name.assert_called_once_with("queue-user", "toyrobot-lo", True)


def test_resolve_returns_the_service_result() -> None:
    boards, services = _make_interface(multiuser=False, user=None)
    services.boards.resolve_by_name.return_value = None

    assert boards.resolve("toyrobot-lo") is None


@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
def test_resolve_rejects_empty_name(name: str) -> None:
    boards, services = _make_interface(multiuser=False, user=None)

    with pytest.raises(ValueError, match="Board name must not be empty."):
        boards.resolve(name)

    services.boards.resolve_by_name.assert_not_called()


def test_resolve_accepts_max_length_name_after_trimming() -> None:
    boards, services = _make_interface(multiuser=False, user=None)
    name = "x" * BOARD_NAME_MAX_LENGTH

    boards.resolve(f"  {name}  ")

    services.boards.resolve_by_name.assert_called_once_with("queue-user", name, False)


def test_resolve_rejects_over_long_name() -> None:
    boards, services = _make_interface(multiuser=False, user=None)

    with pytest.raises(ValueError, match="Board name must be at most 300 characters."):
        boards.resolve("x" * (BOARD_NAME_MAX_LENGTH + 1))

    services.boards.resolve_by_name.assert_not_called()


@pytest.mark.parametrize("is_admin", [True, False])
def test_resolve_uses_queue_user_in_multiuser_mode(is_admin: bool) -> None:
    boards, services = _make_interface(multiuser=True, user=MagicMock(is_admin=is_admin, is_active=True))

    boards.resolve("toyrobot-lo")

    services.users.get.assert_called_once_with("queue-user")
    services.boards.resolve_by_name.assert_called_once_with("queue-user", "toyrobot-lo", False)


@pytest.mark.parametrize(
    "user",
    [None, MagicMock(is_admin=True, is_active=False), MagicMock(is_admin=False, is_active=False)],
)
def test_resolve_rejects_missing_or_deactivated_user_in_multiuser_mode(user: MagicMock | None) -> None:
    boards, services = _make_interface(multiuser=True, user=user)

    with pytest.raises(PermissionError, match="Queue user is not authorized to resolve boards."):
        boards.resolve("toyrobot-lo", create_if_missing=True)

    services.boards.resolve_by_name.assert_not_called()
