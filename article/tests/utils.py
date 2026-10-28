from collection.models import Collection
from package.models import SPSPkg
from pid_provider.models import CollectionPidV2, PidProviderXML


def create_sps_pkg(user, sps_pkg_name, pid_v3=None, collection=None, pid_v2=None):
    """
    Cria SPSPkg vinculado ao documento (PidProviderXML) na coleção
    (CollectionPidV2)
    """
    collection = collection or Collection.objects.get_or_create(
        acron="scl", defaults={"creator": user}
    )[0]
    pid_provider_xml = PidProviderXML.objects.get_or_create(
        v3=pid_v3 or sps_pkg_name, defaults={"creator": user}
    )[0]
    collection_pid_v2 = CollectionPidV2.objects.create(
        creator=user,
        pid_provider_xml=pid_provider_xml,
        collection=collection,
        pid_v2=pid_v2,
        sps_pkg_name=sps_pkg_name,
    )
    return SPSPkg.objects.create(
        creator=user, sps_pkg_name=sps_pkg_name, collection_pid_v2=collection_pid_v2
    )


def link_sps_pkg(user, article, sps_pkg_name, collection=None):
    """Vincula o artigo a um pacote (via CollectionPidV2) e o salva"""
    sps_pkg = create_sps_pkg(
        user, sps_pkg_name, pid_v3=article.pid_v3 or sps_pkg_name, collection=collection
    )
    article.collection_pid_v2 = sps_pkg.collection_pid_v2
    article.save()
    return sps_pkg
