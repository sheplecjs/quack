from web import pipelines
from web.ingestion.shynet import pipeline as shynet
from web.ingestion.shynet_db import pipeline as shynet_db


def test_all_loads_every_source_with_its_defaults(monkeypatch):
    calls = []
    monkeypatch.setattr(
        shynet, "load_shynet", lambda **kwargs: calls.append(("shynet", kwargs))
    )
    monkeypatch.setattr(
        shynet_db,
        "load_shynet_db",
        lambda **kwargs: calls.append(("shynet-db", kwargs)),
    )

    pipelines.main(["all"])

    assert calls == [
        (
            "shynet",
            {"start_date": None, "end_date": None, "resources": None, "refresh": False},
        ),
        ("shynet-db", {"resources": None, "refresh": False}),
    ]


def test_a_named_source_loads_alone(monkeypatch):
    calls = []
    monkeypatch.setattr(
        shynet_db, "load_shynet_db", lambda **kwargs: calls.append(kwargs)
    )
    monkeypatch.setattr(
        shynet, "load_shynet", lambda **kwargs: calls.append("wrong source")
    )

    pipelines.main(["shynet-db", "--refresh"])

    assert calls == [{"resources": None, "refresh": True}]
