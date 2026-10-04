import pytest

from invokeai.app.services.board_records.board_records_common import BoardRecordNameAmbiguousException
from invokeai.app.services.invoker import Invoker


def test_returns_dto_for_existing_board(mock_invoker: Invoker) -> None:
    existing = mock_invoker.services.board_records.save("toyrobot-lo", "user")

    dto = mock_invoker.services.boards.resolve_by_name("user", "toyrobot-lo")

    assert dto is not None
    assert dto.board_id == existing.board_id
    assert dto.board_name == "toyrobot-lo"
    assert dto.image_count == 0
    assert dto.project_id is None


def test_returns_none_when_missing_by_default(mock_invoker: Invoker) -> None:
    assert mock_invoker.services.boards.resolve_by_name("user", "toyrobot-lo") is None


def test_creates_and_returns_dto_when_asked(mock_invoker: Invoker) -> None:
    dto = mock_invoker.services.boards.resolve_by_name("user", "toyrobot-lo", create_if_missing=True)

    assert dto is not None
    assert dto.board_name == "toyrobot-lo"
    assert mock_invoker.services.board_records.get(dto.board_id).user_id == "user"


def test_propagates_ambiguity(mock_invoker: Invoker) -> None:
    mock_invoker.services.board_records.save("toyrobot-lo", "user")
    mock_invoker.services.board_records.save("toyrobot-lo", "user")

    with pytest.raises(BoardRecordNameAmbiguousException):
        mock_invoker.services.boards.resolve_by_name("user", "toyrobot-lo", create_if_missing=True)
