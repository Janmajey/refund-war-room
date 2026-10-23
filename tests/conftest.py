import pytest

import make_data
from war_room.config import DB_PATH, DOCS_DIR
from war_room.docs import DocStore
from war_room.tools import Tools


@pytest.fixture(scope="session")
def docs():
    if not DB_PATH.exists():
        make_data.main()
    return DocStore(DOCS_DIR)


@pytest.fixture
def tools(docs, tmp_path):
    return Tools(DB_PATH, docs, tmp_path / "whatsapp.log")
