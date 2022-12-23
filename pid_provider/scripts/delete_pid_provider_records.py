from .. import models
from files_storage.models import MinioFile


def run():
    models.XMLIssue.objects.all().delete()
    models.XMLJournal.objects.all().delete()
    MinioFile.objects.all().delete()
    models.XMLAOPArticle.objects.all().delete()
    models.XMLArticle.objects.all().delete()
    models.RequestResult.objects.all().delete()
