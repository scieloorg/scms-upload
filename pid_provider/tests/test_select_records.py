from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from pid_provider.models import PidProviderXML


@pytest.fixture
def adapter():
    return SimpleNamespace(
        v3=None, v2=None, aop_pid=None, order=None,
        pkg_name="pacote", sps_pkg_name="pacote",
        data={
            "issn_print": "1234-5678", "pub_year": "2026",
            "volume": "10", "number": "2", "suppl": None,
            "fpage": "10", "fpage_seq": None, "lpage": "20",
            "elocation_id": None, "z_surnames": "autores",
            "z_collab": None, "z_links": None, "z_partial_body": "legado",
        },
        xml_with_pre=SimpleNamespace(
            body_fragment_fingerprint="fragmento",
            deprecated_sps_pkg_name_list=[],
            readable_data={"article_titles": ["Título"]},
        ),
    )


@pytest.fixture
def create_record(db, adapter):
    user = get_user_model().objects.create_user(username="candidate-search")

    def create(**overrides):
        data = dict(adapter.data, pkg_name="pacote")
        data.update(overrides)
        return PidProviderXML.objects.create(creator=user, **data)

    return create


def test_empty_identifiers_do_not_query_or_select_by_package_name(
    adapter, create_record, django_assert_num_queries
):
    create_record(issn_print="9999-9999")
    candidates = PidProviderXML.select_records(adapter)

    with django_assert_num_queries(0):
        assert next(candidates) == ("ids", [])

    assert all(not items for _, items in candidates)


@pytest.mark.parametrize("with_issue", [True, False])
def test_strict_and_flexible_candidates_respect_journal_and_location(
    adapter, create_record, with_issue
):
    if not with_issue:
        for field in ("volume", "number", "fpage", "lpage"):
            adapter.data[field] = None

    exact = create_record()
    corrected = create_record(z_surnames="autores corrigidos")
    create_record(issn_print="9999-9999")
    create_record(fpage="99")

    results = dict(PidProviderXML.select_records(adapter))

    assert list(results) == [
        "ids", "journal-issue-article-strict", "journal-issue-article-flexible"
    ]
    assert results["ids"] == []
    assert results["journal-issue-article-strict"] == [exact]
    assert set(results["journal-issue-article-flexible"]) == {exact, corrected}


def test_identifiers_are_searched_before_metadata(adapter, create_record):
    adapter.v3 = "PID-CANONICO"
    direct = create_record(v3=adapter.v3, issn_print="9999-9999")
    create_record()

    assert next(PidProviderXML.select_records(adapter)) == ("ids", [direct])
