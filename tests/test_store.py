import numpy as np
import pytest

from troubleshooting_agent.retrieval.embeddings import HashEmbedder
from troubleshooting_agent.retrieval.store import NumpyStore, QdrantStore


def _chunk(chunk_id, doc_id, pagina, texto, tipo="general", modelos=("Modelo X",)):
    return {
        "chunk_id": chunk_id, "doc_id": doc_id, "pagina_inicio": pagina, "pagina_fin": pagina,
        "tipo_contenido": tipo, "modelos": list(modelos), "texto": texto,
    }


CHUNKS = [
    _chunk("a::p0001::c00", "a", 1, "sobretensión en el bus DC del variador", "troubleshooting"),
    _chunk("a::p0002::c00", "a", 2, "instalación del gabinete y cableado de potencia", "instalacion"),
    _chunk("b::p0010::c00", "b", 10, "caudalímetro ultrasónico montaje de transductores", modelos=["F532WD"]),
]


@pytest.fixture(params=["qdrant_memoria", "qdrant_disco", "numpy_memoria", "numpy_disco"])
def store(request, tmp_path):
    if request.param == "qdrant_memoria":
        s = QdrantStore(None, "test")
    elif request.param == "qdrant_disco":
        s = QdrantStore(tmp_path / "qdrant", "test")
    elif request.param == "numpy_memoria":
        s = NumpyStore(None)
    else:
        s = NumpyStore(tmp_path / "numpy")
    yield s
    if isinstance(s, QdrantStore):
        s.cerrar()


@pytest.fixture
def emb():
    return HashEmbedder(dim=128)


def _cargar(store, emb, chunks=CHUNKS):
    store.recrear(emb.dim, {"embedding_model": emb.nombre})
    store.upsert(chunks, emb.encode([c["texto"] for c in chunks]))


def test_vacio(store):
    assert store.meta() is None
    assert store.count() == 0


def test_upsert_y_meta(store, emb):
    _cargar(store, emb)
    assert store.count() == 3
    assert store.meta()["embedding_model"] == "hash-embedder"
    assert store.meta()["dim"] == 128


def test_reindexar_no_duplica(store, emb):
    _cargar(store, emb)
    store.upsert(CHUNKS, emb.encode([c["texto"] for c in CHUNKS]))
    assert store.count() == 3


def test_buscar_mas_similar(store, emb):
    _cargar(store, emb)
    hits = store.buscar(emb.encode(["sobretensión bus DC"])[0], k=2)
    assert len(hits) == 2
    assert hits[0].payload["chunk_id"] == "a::p0001::c00"
    assert hits[0].score >= hits[1].score


def test_filtros(store, emb):
    _cargar(store, emb)
    q = emb.encode(["sobretensión bus DC"])[0]
    assert {h.payload["doc_id"] for h in store.buscar(q, 5, {"doc_id": "b"})} == {"b"}
    hits = store.buscar(q, 5, {"tipo_contenido": ["instalacion", "troubleshooting"]})
    assert {h.payload["chunk_id"] for h in hits} == {"a::p0001::c00", "a::p0002::c00"}
    # campo lista: matchea si algún elemento coincide
    assert [h.payload["doc_id"] for h in store.buscar(q, 5, {"modelos": "F532WD"})] == ["b"]
    assert store.buscar(q, 5, {"doc_id": "no-existe"}) == []


def test_numpy_persiste(tmp_path, emb):
    s = NumpyStore(tmp_path / "idx")
    _cargar(s, emb)
    s2 = NumpyStore(tmp_path / "idx")
    assert s2.count() == 3
    q = emb.encode(["caudalímetro"])[0]
    assert s2.buscar(q, 1)[0].payload["doc_id"] == "b"


def test_hash_embedder_normalizado_y_determinista(emb):
    m = emb.encode(["hola mundo", "hola mundo", ""])
    np.testing.assert_allclose(np.linalg.norm(m[:2], axis=1), 1.0, rtol=1e-5)
    np.testing.assert_array_equal(m[0], m[1])
    assert not m[2].any()
