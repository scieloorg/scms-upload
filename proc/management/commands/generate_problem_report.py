"""
Gera o relatório de problemas com a situação atual dos *Proc.

Exemplos (docker):
    docker compose -f local.yml run --rm django \
        python manage.py generate_problem_report --collection scl --journal rsp
    ... generate_problem_report --content-type all
    ... generate_problem_report --async   # delega ao celery
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from proc.models import ProblemReport
from proc.tasks import (
    PROBLEM_REPORT_ITEM_TYPES,
    _problem_report_scope,
    task_generate_problem_report,
)


class Command(BaseCommand):
    help = "Gera o relatório de problemas (BLOCKED/PENDING) com a situação atual dos *Proc"

    def add_arguments(self, parser):
        parser.add_argument(
            "--content-type",
            default="articles",
            choices=sorted(PROBLEM_REPORT_ITEM_TYPES),
            help="articles (fascículos + artigos), issues, journals ou all",
        )
        parser.add_argument("--collection", action="append", default=[], help="acron (repetível)")
        parser.add_argument("--journal", action="append", default=[], help="acron (repetível)")
        parser.add_argument("--year", help="ano de publicação")
        parser.add_argument("--issue-folder")
        parser.add_argument(
            "--updated-from",
            help="itens atualizados a partir de (AAAA-MM-DD ou data-hora ISO)",
        )
        parser.add_argument(
            "--updated-to",
            help="itens atualizados até (AAAA-MM-DD, inclusivo, ou data-hora ISO)",
        )
        parser.add_argument("--username", help="usuário (o idioma preferido dele é usado)")
        parser.add_argument(
            "--language",
            help="en, pt ou es (padrão: idioma do usuário ou LANGUAGE_CODE)",
        )
        parser.add_argument(
            "--max-items",
            type=int,
            help="máximo de itens com problema (conforme a capacidade da máquina; padrão 100000)",
        )
        parser.add_argument(
            "--async",
            dest="run_async",
            action="store_true",
            help="agenda no celery em vez de gerar nesta execução",
        )

    def handle(self, *args, **options):
        kwargs = dict(
            content_type=options["content_type"],
            collection_acron_list=options["collection"],
            journal_acron_list=options["journal"],
            publication_year=options["year"],
            issue_folder=options["issue_folder"],
            updated_from=options["updated_from"],
            updated_to=options["updated_to"],
        )
        if options["run_async"]:
            task_generate_problem_report.delay(
                username=options["username"],
                language=options["language"],
                max_items=options["max_items"],
                triggered_by="manage.py generate_problem_report",
                **kwargs,
            )
            self.stdout.write("Agendado no celery.")
            return

        user = None
        if options["username"]:
            user = get_user_model().objects.filter(username=options["username"]).first()

        scope = _problem_report_scope(
            collection_acron_list=kwargs["collection_acron_list"],
            journal_acron_list=kwargs["journal_acron_list"],
            publication_year=kwargs["publication_year"],
            issue_folder=kwargs["issue_folder"],
            updated_from=kwargs["updated_from"],
            updated_to=kwargs["updated_to"],
        )
        report = ProblemReport.generate(
            scope,
            PROBLEM_REPORT_ITEM_TYPES[kwargs["content_type"]],
            user=user,
            task_name="manage.py generate_problem_report",
            language=options["language"],
            max_items=options["max_items"],
        )
        self.stdout.write(
            f"{report.scope_label}: {report.total_items} itens, "
            f"{report.total_categories} categorias"
        )
        self.stdout.write(f"Idioma: {report.language}")
        self.stdout.write(f"Status: {report.get_status_display()} — analisados/com problema: {report.coverage()}")
        if report.notice:
            self.stdout.write(report.notice)
        self.stdout.write(f"Arquivo: {report.file.name}")
        for name in (report.stats or {}).get("files", []):
            self.stdout.write(f"  - {name}")
        for group in (report.stats or {}).get("top_categories", [])[:10]:
            self.stdout.write(
                f"  {group['code']} {group['total']:>6}  {group['item_type']:<8} {group['kind']:<16} "
                f"{group['operation']} | {group['exception_type']} | "
                f"{group['message_template'][:80]}"
            )
