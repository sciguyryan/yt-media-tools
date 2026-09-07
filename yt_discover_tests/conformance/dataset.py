from copy import deepcopy

GENERATOR_VERSION = 1
SEED = 31415926

_ROWS = [
    {
        "id": "alpha001",
        "title": "Alpha Launch",
        "uploader": "Example One",
        "duration": 90,
        "date": "2024-01-05",
        "live": False,
    },
    {
        "id": "beta002",
        "title": "Beta Review",
        "uploader": "Example Two",
        "duration": 245,
        "date": "2024-01-05",
        "live": False,
    },
    {
        "id": "gamma003",
        "title": "Gamma Live",
        "uploader": "Example One",
        "duration": None,
        "date": "2024-02-10",
        "live": True,
    },
    {"id": "delta004", "title": "Delta Notes", "uploader": None, "duration": 45, "date": None, "live": False},
]


def generate_rows():
    return deepcopy(_ROWS)
