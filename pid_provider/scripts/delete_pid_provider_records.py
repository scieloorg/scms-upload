from .. import models


def run():
    models.XMLIssue.objects.all().delete()
    models.XMLJournal.objects.all().delete()
    models.XMLFile.objects.all().delete()
    models.XMLAOPArticle.objects.all().delete()
    models.XMLArticle.objects.all().delete()
    models.RequestResult.objects.all().delete()
