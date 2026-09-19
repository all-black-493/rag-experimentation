from app.retrieval import catalog as catalog_module
from app.retrieval.catalog import Catalog, CatalogHolder


def test_holder_rebuilds_only_after_the_ttl(monkeypatch):
    builds = []
    monkeypatch.setattr(catalog_module, "build_catalog", lambda client: builds.append(1) or Catalog(collections=[]))
    clock = [1000.0]
    monkeypatch.setattr(catalog_module.time, "monotonic", lambda: clock[0])
    holder = CatalogHolder(client=object(), ttl_seconds=60)

    holder.current()
    holder.current()
    assert len(builds) == 1

    clock[0] += 61
    holder.current()
    assert len(builds) == 2


def test_refresh_rebuilds_immediately(monkeypatch):
    builds = []
    monkeypatch.setattr(catalog_module, "build_catalog", lambda client: builds.append(1) or Catalog(collections=[]))
    holder = CatalogHolder(client=object(), ttl_seconds=3600)

    holder.current()
    holder.refresh()
    assert len(builds) == 2
