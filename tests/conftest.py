import json

import pytest

from fleetaudit import db, score
from fleetaudit.generate import generate, write, write_truth


@pytest.fixture(scope="session")
def book():
    return generate(7)


@pytest.fixture(scope="session")
def data_dir(book, tmp_path_factory):
    d = tmp_path_factory.mktemp("book")
    write(book, d / "book")
    write_truth(book, d / "truth.json")
    return d


@pytest.fixture(scope="session")
def truth(data_dir):
    return json.loads((data_dir / "truth.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def con(data_dir):
    c = db.connect(data_dir / "book")
    yield c
    c.close()


@pytest.fixture(scope="session")
def audit(con):
    return score.run(con)
