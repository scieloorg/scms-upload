"""
Módulo responsável pela migração de dados do site clássico e processamento de PIDs.
"""

import itertools
import logging
import sys

from migration import controller
from migration.models import MigratedArticle, MigratedFile
from proc import choices as proc_choices
from proc.models import (
    ArticleProc,
    IssueProc,
    JournalProc,
)
from tracker import choices as tracker_choices
from tracker.models import UnexpectedEvent


def create_or_update_migrated_journal(
    user,
    collection,
    classic_website,
    force_update,
):
    """
    Cria ou atualiza journals migrados do site clássico.
    """
    has_changes = controller.id_file_has_changes(
        user,
        collection,
        classic_website.classic_website_paths.title_path,
        force_update,
    )
    if not has_changes:
        logging.info(f"skip reading {classic_website.classic_website_paths.title_path}")
        return

    for (
        scielo_issn,
        journal_data,
    ) in classic_website.get_journals_pids_and_records():
        # para cada registro da base de dados "title",
        # cria um registro MigratedData (source="journal")
        try:
            JournalProc.register_classic_website_data(
                user,
                collection,
                scielo_issn,
                journal_data[0],
                "journal",
                force_update,
            )

        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            UnexpectedEvent.create(
                e=e,
                exc_traceback=exc_traceback,
                detail={
                    "task": "proc.sources.classic_website.create_or_update_migrated_journal",
                    "user_id": user.id,
                    "username": user.username,
                    "collection": collection.acron,
                    "pid": scielo_issn,
                    "force_update": force_update,
                },
            )


def create_or_update_migrated_issue(
    user,
    collection,
    classic_website,
    force_update,
):
    """
    Cria ou atualiza issues migrados do site clássico.
    """
    has_changes = controller.id_file_has_changes(
        user,
        collection,
        classic_website.classic_website_paths.issue_path,
        force_update,
    )

    if not has_changes:
        logging.info(f"skip reading {classic_website.classic_website_paths.issue_path}")
        return

    for (
        pid,
        issue_data,
    ) in classic_website.get_issues_pids_and_records():
        # para cada registro da base de dados "issue",
        # cria um registro MigratedData (source="issue")
        try:
            IssueProc.register_classic_website_data(
                user,
                collection,
                pid,
                issue_data[0],
                "issue",
                force_update,
            )

        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            UnexpectedEvent.create(
                e=e,
                exc_traceback=exc_traceback,
                detail={
                    "task": "proc.sources.classic_website.create_or_update_migrated_issue",
                    "user_id": user.id,
                    "username": user.username,
                    "collection": collection.acron,
                    "pid": pid,
                    "force_update": force_update,
                },
            )


def create_collection_procs_from_pid_list(
    user,
    collection,
    pid_list_path,
    force_update,
):
    """
    Cria procs de collection baseado numa lista de PIDs.
    Processa PIDs de artigos, issues e journals de forma hierárquica.
    """
    has_changes = controller.id_file_has_changes(
        user,
        collection,
        pid_list_path,
        force_update,
    )
    if not has_changes:
        logging.info(f"skip reading {pid_list_path}")
        return

    try:
        pid = None
        journal_pids = set()
        issue_pids = set()
        with open(pid_list_path, "r") as fp:
            pids = fp.readlines()

        for pid in pids:
            pid = pid.strip() or ""
            if not len(pid) == 23:
                continue

            # Registra PID do artigo
            ArticleProc.register_pid(
                user,
                collection,
                pid,
                force_update=False,
            )

            # Extrai e registra PID do issue
            issue_pid = pid[1:-5]
            if issue_pid not in issue_pids:
                issue_pids.add(issue_pid)
                IssueProc.register_pid(
                    user,
                    collection,
                    issue_pid,
                    force_update=False,
                )

                # Extrai e registra PID do journal
                journal_pid = pid[1:10]
                if journal_pid not in journal_pids:
                    journal_pids.add(journal_pid)
                    JournalProc.register_pid(
                        user,
                        collection,
                        journal_pid,
                        force_update=False,
                    )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.sources.classic_website.create_collection_procs_from_pid_list",
                "user_id": user.id,
                "username": user.username,
                "collection": collection.acron,
                "pid_list_path": pid_list_path,
                "force_update": force_update,
            },
        )


def migrate_journal(
    user,
    journal_proc,
    force_update,
):
    """
    Executa a migração de um journal específico do site clássico.
    """
    try:
        event = None
        detail = None
        detail = {
            "journal_proc": str(journal_proc),
            "force_update": force_update,
        }
        event = journal_proc.start(user, "create or update journal")

        # cria ou atualiza Journal e atualiza journal_proc
        completed = journal_proc.create_or_update_item(
            user, force_update, controller.create_or_update_journal
        )
        event.finish(user, completed=bool(completed), detail=detail)

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        if event:
            event.finish(
                user,
                completed=False,
                detail=detail,
                exception=e,
                exc_traceback=exc_traceback,
            )
            return

        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.sources.classic_website.migrate_journal",
                "user_id": user.id,
                "username": user.username,
                "collection": journal_proc.collection.acron,
                "pid": journal_proc.pid,
                "force_update": force_update,
            },
        )


def create_or_update_journal_acron_id_file(
    user, collection, journal_filter, force_update=None
):
    """
    Cria ou atualiza arquivos de ID baseados em acrônimos de journals.
    """
    items = JournalProc.objects.select_related(
        "collection",
        "journal",
    ).filter(
        collection=collection,
        **journal_filter,
    )
    logging.info(f"create_or_update_journal_acron_id_file - JournalProc params: collection={collection.acron}, journal_filter={journal_filter} - {items.count()} items found")
    for journal_proc in items:
        logging.info(f"create_or_update_journal_acron_id_file - JournalProc {journal_proc}")
        controller.register_acron_id_file_content(
            user,
            journal_proc,
            force_update=force_update,
        )


def migrate_issue(user, issue_proc, force_update):
    """
    Executa a migração de um issue específico do site clássico.
    """
    try:
        event = None
        detail = None
        detail = {
            "issue_proc": str(issue_proc),
            "force_update": force_update,
        }
        event = issue_proc.start(user, "create or update issue")
        collection = issue_proc.collection
        issue_proc.create_or_update_item(
            user,
            force_update,
            controller.create_or_update_issue,
            JournalProc=JournalProc,
        )
        event.finish(user, completed=True, detail=detail)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        if event:
            event.finish(
                user,
                completed=False,
                detail=detail,
                exception=e,
                exc_traceback=exc_traceback,
            )
            return

        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.sources.classic_website.migrate_issue",
                "user_id": user.id,
                "username": user.username,
                "collection": issue_proc.collection.acron,
                "pid": issue_proc.pid,
                "force_update": force_update,
            },
        )


def migrate_document_records(
    user,
    collection_acron=None,
    journal_acron=None,
    issue_folder=None,
    publication_year=None,
    status=None,
    force_update=None,
    skip_migrate_pending_document_records=None,
):
    """
    Executa a migração de registros de documentos do site clássico.
    """
    params = {}
    if collection_acron:
        params["collection__acron"] = collection_acron
    if journal_acron:
        params["journal_proc__acron"] = journal_acron
    if issue_folder:
        params["issue_folder"] = str(issue_folder)
    if publication_year:
        params["issue__publication_year"] = str(publication_year)
    if status:
        params["docs_status__in"] = tracker_choices.get_valid_status(
            status, force_update
        )

    logging.info(f"migrate_document_records - IssueProc params: {params}")
    for issue_proc in IssueProc.objects.select_related(
        "collection",
        "journal_proc",
        "issue",
    ).filter(**params):
        logging.info(f"migrate_document_records - IssueProc {issue_proc}")
        issue_proc.migrate_document_records(user, force_update)
        ArticleProc.mark_for_reprocessing(issue_proc)

    # if skip_migrate_pending_document_records:
    #     return

    # IssueProc.migrate_pending_document_records(
    #     user,
    #     collection_acron,
    #     journal_acron,
    #     issue_folder,
    #     publication_year,
    # )


def get_files_from_classic_website(
    user,
    collection_acron=None,
    journal_acron=None,
    issue_folder=None,
    publication_year=None,
    status=None,
    force_update=None,
):
    """
    Obtém arquivos do site clássico para processamento.
    """
    params = {}
    if collection_acron:
        params["collection__acron"] = collection_acron
    if journal_acron:
        params["journal_proc__acron"] = journal_acron
    if issue_folder:
        params["issue_folder"] = str(issue_folder)
    if publication_year:
        params["issue__publication_year"] = str(publication_year)
    if status:
        params["files_status__in"] = tracker_choices.get_valid_status(
            status, force_update
        )
    items = IssueProc.objects.select_related(
        "collection",
        "journal_proc",
        "issue",
    ).filter(**params)
    logging.info(f"get_files_from_classic_website - IssueProc params: {params} - {items.count()} items found")
    for issue_proc in items:
        logging.info(f"get_files_from_classic_website - IssueProc {issue_proc}")
        issue_proc.get_files_from_classic_website(
            user, force_update, controller.migrate_issue_files
        )
        ArticleProc.mark_for_reprocessing(issue_proc)


BATCH_SIZE = 1000
SAMPLE_SIZE = 10
PID_V2_LENGTH = 23


class ClassicWebsiteArticlePidTracker:
    """Tracks PIDs between the classic website PID list and ArticleProc records.

    Stores the PID list as a MigratedFile instance. On subsequent runs,
    retrieves the previous version, computes a diff, and processes only
    the differences. Use force_update=True to process the full list.

    Processes data in batches to avoid memory issues with large datasets
    (500k+ PIDs).
    """

    TASK_NAME = "proc.source_classic_website.track_classic_website_article_pids"

    def __init__(self, user, collection, classic_website_config, force_update=False):
        self.user = user
        self.collection = collection
        self.classic_website_config = classic_website_config
        self.pid_list_path = classic_website_config.pid_list_path
        self.force_update = force_update
        self.missing_total = 0
        self.matched_total = 0
        self.exceeding_total = 0

    @staticmethod
    def _iter_batches(iterable, batch_size):
        """Yield successive batches from an iterable without converting to list."""
        it = iter(iterable)
        while True:
            batch = list(itertools.islice(it, batch_size))
            if not batch:
                break
            yield batch

    def _get_stored_pid_list(self):
        """Retrieve the previously stored PID list from MigratedFile.

        Returns a set of PIDs parsed from the stored file content,
        or an empty set if no previous version exists.
        """
        if not self.pid_list_path:
            return set()
        try:
            migrated_file = MigratedFile.get(self.collection, self.pid_list_path)
            if migrated_file.file:
                content = migrated_file.file.read().decode("utf-8")
                return {
                    line.strip()
                    for line in content.splitlines()
                    if len(line.strip()) == PID_V2_LENGTH
                }
        except MigratedFile.DoesNotExist:
            pass
        except Exception as e:
            logging.exception(
                "Error reading stored PID list for %s: %s",
                self.pid_list_path,
                e,
            )
        return set()

    def _store_pid_list(self):
        """Store/update the current PID list file as a MigratedFile instance."""
        if not self.pid_list_path:
            return
        try:
            MigratedFile.create_or_update(
                user=self.user,
                collection=self.collection,
                original_path=self.pid_list_path,
                source_path=self.pid_list_path,
                component_type="pid_list",
                force_update=self.force_update,
            )
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            UnexpectedEvent.create(
                e=e,
                exc_traceback=exc_traceback,
                detail={
                    "task": self.TASK_NAME,
                    "step": "store_pid_list",
                    "collection": self.collection.acron,
                    "pid_list_path": self.pid_list_path,
                },
            )

    def _process_pid(self, pid):
        """Create MigratedArticle and ArticleProc for a PID, link them.

        Returns "missing" or "matched" based on MigratedArticle data presence.
        """
        migrated_article = MigratedArticle.create_or_update_migrated_data(
            user=self.user,
            collection=self.collection,
            pid=pid,
            content_type="article",
        )
        article_proc = ArticleProc.get_or_create(self.user, self.collection, pid)
        if not article_proc.migrated_data:
            article_proc.migrated_data = migrated_article
            article_proc.save()

        if migrated_article.data is None or migrated_article.data == {}:
            return proc_choices.PID_STATUS_MISSING
        return proc_choices.PID_STATUS_MATCHED

    def _process_pids(self, pids_to_process):
        """Process PIDs in batches: create records and classify pid_status."""
        for batch in self._iter_batches(pids_to_process, BATCH_SIZE):
            missing_pids = []
            matched_pids = []

            for pid in batch:
                try:
                    status = self._process_pid(pid)
                    if status == proc_choices.PID_STATUS_MISSING:
                        missing_pids.append(pid)
                    else:
                        matched_pids.append(pid)
                except Exception as e:
                    exc_type, exc_value, exc_traceback = sys.exc_info()
                    UnexpectedEvent.create(
                        e=e,
                        exc_traceback=exc_traceback,
                        detail={
                            "task": self.TASK_NAME,
                            "step": "create_or_update_pid",
                            "pid": pid,
                            "collection": self.collection.acron,
                        },
                    )

            if missing_pids:
                ArticleProc.objects.filter(
                    collection=self.collection, pid__in=missing_pids
                ).update(pid_status=proc_choices.PID_STATUS_MISSING)
                self.missing_total += len(missing_pids)

            if matched_pids:
                ArticleProc.objects.filter(
                    collection=self.collection, pid__in=matched_pids
                ).update(pid_status=proc_choices.PID_STATUS_MATCHED)
                self.matched_total += len(matched_pids)

    def _mark_exceeding_batch(self, pids_batch, message):
        """Mark a batch of PIDs as exceeding and create an UnexpectedEvent."""
        ArticleProc.objects.filter(
            collection=self.collection, pid__in=pids_batch
        ).update(pid_status=proc_choices.PID_STATUS_EXCEEDING)
        UnexpectedEvent.create(
            e=Exception(message),
            exc_traceback=None,
            detail={
                "task": self.TASK_NAME,
                "step": "exceeding_article_proc",
                "collection": self.collection.acron,
                "total": len(pids_batch),
                "sample": pids_batch[:SAMPLE_SIZE],
            },
        )

    def _detect_exceeding_diff_mode(self, removed_pids):
        """Diff mode: mark removed PIDs as exceeding."""
        for batch in self._iter_batches(removed_pids, BATCH_SIZE):
            self._mark_exceeding_batch(
                batch, "ArticleProc PIDs removed from classic website PID list"
            )
            self.exceeding_total += len(batch)

    def _detect_exceeding_full_mode(self, classic_pids):
        """Full mode: scan all ArticleProcs not in classic PID list.

        Also delegates to _detect_exceeding_migrated_articles for
        MigratedArticle scanning.
        """
        exceeding_pids_batch = []
        for article_proc in (
            ArticleProc.objects.filter(collection=self.collection)
            .only("pid", "pid_status")
            .iterator(chunk_size=BATCH_SIZE)
        ):
            if article_proc.pid not in classic_pids:
                exceeding_pids_batch.append(article_proc.pid)
                self.exceeding_total += 1

                if len(exceeding_pids_batch) >= BATCH_SIZE:
                    self._mark_exceeding_batch(
                        exceeding_pids_batch,
                        "ArticleProc PIDs not in classic website PID list",
                    )
                    exceeding_pids_batch = []

        if exceeding_pids_batch:
            self._mark_exceeding_batch(
                exceeding_pids_batch,
                "ArticleProc PIDs not in classic website PID list",
            )

        self._detect_exceeding_migrated_articles(classic_pids)

    def _detect_exceeding_migrated_articles(self, classic_pids):
        """Full mode: detect MigratedArticle PIDs not in classic PID list."""
        exceeding_migrated_pids = []
        for migrated in (
            MigratedArticle.objects.filter(collection=self.collection)
            .only("pid")
            .iterator(chunk_size=BATCH_SIZE)
        ):
            if migrated.pid not in classic_pids:
                exceeding_migrated_pids.append(migrated.pid)

                if len(exceeding_migrated_pids) >= BATCH_SIZE:
                    UnexpectedEvent.create(
                        e=Exception(
                            "MigratedArticle PIDs not in classic website PID list"
                        ),
                        exc_traceback=None,
                        detail={
                            "task": self.TASK_NAME,
                            "step": "exceeding_migrated_article",
                            "collection": self.collection.acron,
                            "total": len(exceeding_migrated_pids),
                            "sample": exceeding_migrated_pids[:SAMPLE_SIZE],
                        },
                    )
                    exceeding_migrated_pids = []

        if exceeding_migrated_pids:
            UnexpectedEvent.create(
                e=Exception(
                    "MigratedArticle PIDs not in classic website PID list"
                ),
                exc_traceback=None,
                detail={
                    "task": self.TASK_NAME,
                    "step": "exceeding_migrated_article",
                    "collection": self.collection.acron,
                    "total": len(exceeding_migrated_pids),
                    "sample": exceeding_migrated_pids[:SAMPLE_SIZE],
                },
            )

    def _build_result(self, classic_pids):
        """Build the summary result dict."""
        migrated_total = self.matched_total + self.missing_total
        return {
            "collection": self.collection.acron,
            "classic_website_total": len(classic_pids),
            "migrated_total": migrated_total,
            "items": [
                {
                    "type": "MISSING",
                    "criticality": "CRITICAL",
                    "description": "PIDs in classic website but MigratedArticle has no data",
                    "total": self.missing_total,
                },
                {
                    "type": "MATCHED",
                    "criticality": "INFO",
                    "description": "PIDs in classic website with MigratedArticle data",
                    "total": self.matched_total,
                },
                {
                    "type": "EXCEEDING",
                    "criticality": "WARNING",
                    "description": "PIDs in ArticleProc/MigratedArticle but absent from classic website PID list",
                    "total": self.exceeding_total,
                },
            ],
        }

    def run(self):
        """Execute PID tracking. Returns a summary dict or None."""
        try:
            classic_pids = self.classic_website_config.pid_list
            if not classic_pids:
                logging.warning(
                    "No PIDs found from classic website for collection %s",
                    self.collection.acron,
                )
                return None

            previous_pids = set()
            if not self.force_update:
                previous_pids = self._get_stored_pid_list()

            self._store_pid_list()

            if previous_pids and not self.force_update:
                pids_to_process = classic_pids - previous_pids
                removed_pids = previous_pids - classic_pids
            else:
                pids_to_process = classic_pids
                removed_pids = set()

            self._process_pids(pids_to_process)

            if previous_pids and not self.force_update:
                self._detect_exceeding_diff_mode(removed_pids)
            else:
                self._detect_exceeding_full_mode(classic_pids)

            result = self._build_result(classic_pids)

            logging.info(
                "PID tracking for %s: classic=%d, missing=%d, matched=%d, exceeding=%d",
                self.collection.acron,
                len(classic_pids),
                self.missing_total,
                self.matched_total,
                self.exceeding_total,
            )

            return result

        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            UnexpectedEvent.create(
                e=e,
                exc_traceback=exc_traceback,
                detail={
                    "task": self.TASK_NAME,
                    "user_id": self.user.id if self.user else None,
                    "username": self.user.username if self.user else None,
                    "collection": self.collection.acron if self.collection else None,
                },
            )
            return None


def track_classic_website_article_pids(
    user, collection, classic_website_config, force_update=False
):
    """Compares the PID list from the classic website with ArticleProc records.

    Delegates to ClassicWebsiteArticlePidTracker.run().
    """
    tracker = ClassicWebsiteArticlePidTracker(
        user, collection, classic_website_config, force_update
    )
    return tracker.run()
