from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre

from article.models import Article
from issue.models import Issue
from journal.models import Journal
from package.models import SPSPkg
from pid_provider.models import PidProviderXML


XML_PATH = (
    Path(__file__).resolve().parents[1]
    / "pid_provider/fixtures/sub-article/2236-8906-hoehnea-49-e1082020.xml"
)


@pytest.fixture
def identity(db, django_user_model):
    user = django_user_model.objects.create_user(username="package-identity")
    ppx = PidProviderXML.objects.create(
        creator=user, v3="PID-CANONICO", v2="PID-V2", pkg_name="pacote",
        readable_data={"article_titles": ["Título"]},
    )
    return user, ppx


@pytest.fixture
def register_package(identity):
    user, ppx = identity

    def register(**overrides):
        params = dict(
            pid_v3=ppx.v3, pid_v2=ppx.v2, sps_pkg_name=ppx.pkg_name,
            registered_in_core=True, ppx_id=ppx.pk,
        )
        params.update(overrides)
        return SPSPkg._get_or_create(user, **params)

    return register


def test_pid_response_links_package_and_reprocessing_reuses_identity(identity):
    user, ppx = identity
    package_id = None
    for name in ("pacote", "pacote-renomeado"):
        response = dict(ppx.data, xml_with_pre=SimpleNamespace(sps_pkg_name=name))
        with patch(
            "package.models.pid_provider_app.request_pid_for_xml_zip",
            return_value=iter([response]),
        ):
            package = SPSPkg._add_pid_v3_to_zip(
                user, "package.zip", False, MagicMock(), "xml.zip"
            )
        package.refresh_from_db()
        assert package.ppx_id == ppx.pk
        assert package.sps_pkg_name == name
        if package_id is not None:
            assert package.pk == package_id
        package_id = package.pk
    assert SPSPkg.objects.count() == 1


def test_adopts_unlinked_package_without_reassigning_other_identity(identity, register_package):
    user, ppx = identity
    other = PidProviderXML.objects.create(creator=user, v3="OUTRO-PID")
    linked = SPSPkg.objects.create(
        creator=user, ppx=other, sps_pkg_name=ppx.pkg_name, pid_v3=ppx.v3
    )
    legacy = SPSPkg.objects.create(creator=user, pid_v3=ppx.v3)

    assert register_package().pk == legacy.pk
    linked.refresh_from_db()
    assert linked.ppx_id == other.pk
    assert SPSPkg.objects.count() == 2


@pytest.mark.parametrize("conflicting", [True, False])
def test_legacy_duplicates_are_preserved_and_conflicts_block_update(
    identity, register_package, conflicting
):
    user, ppx = identity
    first = SPSPkg.objects.create(
        creator=user, pid_v3=ppx.v3, pid_v2=ppx.v2, sps_pkg_name=ppx.pkg_name
    )
    second = SPSPkg.objects.create(
        creator=user, pid_v3="OUTRO" if conflicting else ppx.v3,
        pid_v2=ppx.v2, sps_pkg_name=ppx.pkg_name,
    )
    if conflicting:
        with pytest.raises(SPSPkg.MultipleObjectsReturned):
            register_package()
        assert not SPSPkg.objects.filter(ppx__isnull=False).exists()
    else:
        assert register_package().pk == second.pk
    assert set(SPSPkg.objects.values_list("pk", flat=True)) == {first.pk, second.pk}


def test_missing_identity_blocks_package_creation(register_package):
    with pytest.raises(ValueError, match="requires ppx_id"):
        register_package(ppx_id=None)
    assert not SPSPkg.objects.exists()


def test_article_reuses_package_and_its_explicit_pid_record(identity, register_package):
    user, ppx = identity
    package = register_package()
    other_ppx = PidProviderXML.objects.create(creator=user, v3=ppx.v3)
    other_package = SPSPkg.objects.create(
        creator=user, ppx=other_ppx, pid_v3=ppx.v3, sps_pkg_name=ppx.pkg_name
    )
    unrelated = Article.objects.create(
        creator=user, sps_pkg=other_package, pid_v3="OUTRO-ARTIGO"
    )
    journal = Journal.objects.create(creator=user, short_title="Journal")
    issue = Issue.objects.create(creator=user, journal=journal)
    xml = next(XMLWithPre.create(path=str(XML_PATH)))
    with patch.object(
        SPSPkg, "xml_with_pre", new_callable=PropertyMock, return_value=xml
    ):
        article = Article.create_or_update(user, package, issue, journal, position=1)
        repeated = Article.create_or_update(user, package, issue, journal, position=1)

    article.refresh_from_db()
    assert repeated.pk == article.pk
    assert article.pp_xml_id == ppx.pk
    assert article.pid_v2 == package.pid_v2
    assert Article.objects.filter(pk=unrelated.pk).exists()
    assert Article.objects.count() == 2
