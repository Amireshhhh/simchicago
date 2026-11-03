import pytest

from simchi.pipeline import build


@pytest.fixture(scope="session")
def built():
    return build(2000, seed=1)
