"""
Revisa conversões HTML -> XML já feitas, sem reconverter: grava as
categorias de problema de cada conversão (Processing > HTML to XML review).

Exemplos (docker):
    docker compose -f local.yml run --rm django \\
        python manage.py review_html2xml --collection scl --journal rsp
    ... review_html2xml --only-not-reviewed
    ... review_html2xml --async        # delega ao celery
"""

from django.core.management.base import BaseCommand

from htmlxml.review import queryset_to_review, review_many
from htmlxml.tasks import task_review_html2xml


class Command(BaseCommand):
    help = "Revisa conversões HTML -> XML já feitas (categorias de problema)"

    def add_arguments(self, parser):
        parser.add_argument("--collection", action="append", default=[], help="acron (repetível)")
        parser.add_argument("--journal", action="append", default=[], help="acron (repetível)")
        parser.add_argument("--updated-from", help="convertidos a partir de (AAAA-MM-DD)")
        parser.add_argument("--updated-to", help="convertidos até (AAAA-MM-DD, inclusivo)")
        parser.add_argument("--only-not-reviewed", action="store_true", help="só as ainda não revisadas")
        parser.add_argument("--limit", type=int, help="máximo de conversões")
        parser.add_argument("--async", dest="run_async", action="store_true", help="agenda no celery")

    def handle(self, *args, **options):
        params = dict(
            collection_acron_list=options["collection"],
            journal_acron_list=options["journal"],
            updated_from=options["updated_from"],
            updated_to=options["updated_to"],
            only_not_reviewed=options["only_not_reviewed"],
        )
        if options["run_async"]:
            task_review_html2xml.delay(limit=options["limit"], **params)
            self.stdout.write("Agendado no celery.")
            return
        result = review_many(queryset_to_review(**params), limit=options["limit"])
        self.stdout.write(f"Revisadas: {sum(result.values())}")
        self.stdout.write(f"Por gravidade: {result}")
