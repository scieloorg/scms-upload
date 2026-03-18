"""
Módulo responsável pela migração de dados do site clássico e processamento de PIDs.
"""

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


class ClassicWebsiteArticlePidTracker:
    """Tracks PIDs between the classic website PID list and ArticleProc records.

    Stores the PID list as a MigratedFile instance. On subsequent runs,
    retrieves the previous version via get_lines(), computes a diff,
    and processes only the differences. Use force_update=True to process
    the full list.
    """

    TASK_NAME = "proc.source_classic_website.track_classic_website_article_pids"

    def __init__(self, user, collection, pid_list_path, force_update=False):
        self.user = user
        self.collection = collection
        self.pid_list_path = pid_list_path
        self.force_update = force_update
        self.missing_total = 0
        self.matched_total = 0
        self.exceeding_total = 0
        self.current_pids = set()
        self._previous_pids = set()
        self._removed_pids = set()

    def _store_pid_list(self):
        """Store/update the PID list file as a MigratedFile instance."""
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

    def _get_migrated_file_pids(self):
        """Get PIDs from the stored MigratedFile via get_lines()."""
        if not self.pid_list_path:
            return set()
        try:
            migrated_file = MigratedFile.get(self.collection, self.pid_list_path)
            return set(migrated_file.get_lines())
        except MigratedFile.DoesNotExist:
            return set()
        except Exception as e:
            logging.exception("Error reading stored PID list: %s", e)
            return set()

    def get_pids_to_process(self):
        """Compute PIDs to process. Stores PID list and computes diff.

        Sets self.current_pids, self._previous_pids, self._removed_pids.
        Returns the set of PIDs to add/process.
        """
        if not self.force_update:
            self._previous_pids = self._get_migrated_file_pids()

        self._store_pid_list()
        self.current_pids = self._get_migrated_file_pids()

        if self._previous_pids and not self.force_update:
            self._removed_pids = self._previous_pids - self.current_pids
            return self.current_pids - self._previous_pids
        return self.current_pids

    def _process_pid(self, pid):
        """Create MigratedArticle and ArticleProc for a PID, link them.

        Returns pid_status based on MigratedArticle data presence.
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

    def _flush_status_batch(self, pids, status):
        """Bulk update pid_status for a list of PIDs."""
        if pids:
            ArticleProc.objects.filter(
                collection=self.collection, pid__in=pids
            ).update(pid_status=status)

    def _process_pids(self):
        """Process PIDs: create records and classify pid_status."""
        pids_to_add = self.get_pids_to_process()
        missing_pids, matched_pids = [], []

        for pid in pids_to_add:
            try:
                status = self._process_pid(pid)
                if status == proc_choices.PID_STATUS_MISSING:
                    missing_pids.append(pid)
                else:
                    matched_pids.append(pid)

                if len(missing_pids) >= BATCH_SIZE:
                    self._flush_status_batch(
                        missing_pids, proc_choices.PID_STATUS_MISSING
                    )
                    self.missing_total += len(missing_pids)
                    missing_pids = []

                if len(matched_pids) >= BATCH_SIZE:
                    self._flush_status_batch(
                        matched_pids, proc_choices.PID_STATUS_MATCHED
                    )
                    self.matched_total += len(matched_pids)
                    matched_pids = []
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

        self._flush_status_batch(missing_pids, proc_choices.PID_STATUS_MISSING)
        self.missing_total += len(missing_pids)
        self._flush_status_batch(matched_pids, proc_choices.PID_STATUS_MATCHED)
        self.matched_total += len(matched_pids)

    def _mark_exceeding_batch(self, pids_batch, message):
        """Mark a batch of PIDs as exceeding with aggregated UnexpectedEvent."""
        self._flush_status_batch(pids_batch, proc_choices.PID_STATUS_EXCEEDING)
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

    def _detect_exceeding(self):
        """Detect exceeding PIDs based on mode (diff or full)."""
        if self._previous_pids and not self.force_update:
            self._detect_exceeding_diff_mode()
        else:
            self._detect_exceeding_full_mode()

    def _detect_exceeding_diff_mode(self):
        """Diff mode: mark removed PIDs as exceeding."""
        batch = []
        for pid in self._removed_pids:
            batch.append(pid)
            if len(batch) >= BATCH_SIZE:
                self._mark_exceeding_batch(
                    batch,
                    "ArticleProc PIDs removed from classic website PID list",
                )
                self.exceeding_total += len(batch)
                batch = []
        if batch:
            self._mark_exceeding_batch(
                batch,
                "ArticleProc PIDs removed from classic website PID list",
            )
            self.exceeding_total += len(batch)

    def _detect_exceeding_full_mode(self):
        """Full mode: scan ArticleProcs and MigratedArticles not in PID list."""
        self._scan_exceeding_article_procs()
        self._scan_exceeding_migrated_articles()

    def _scan_exceeding_article_procs(self):
        """Scan ArticleProcs for PIDs not in current PID list."""
        batch = []
        for ap in (
            ArticleProc.objects.filter(collection=self.collection)
            .only("pid")
            .iterator(chunk_size=BATCH_SIZE)
        ):
            if ap.pid not in self.current_pids:
                batch.append(ap.pid)
                self.exceeding_total += 1
                if len(batch) >= BATCH_SIZE:
                    self._mark_exceeding_batch(
                        batch,
                        "ArticleProc PIDs not in classic website PID list",
                    )
                    batch = []
        if batch:
            self._mark_exceeding_batch(
                batch, "ArticleProc PIDs not in classic website PID list"
            )

    def _scan_exceeding_migrated_articles(self):
        """Scan MigratedArticles for PIDs not in current PID list."""
        batch = []
        for ma in (
            MigratedArticle.objects.filter(collection=self.collection)
            .only("pid")
            .iterator(chunk_size=BATCH_SIZE)
        ):
            if ma.pid not in self.current_pids:
                batch.append(ma.pid)
                if len(batch) >= BATCH_SIZE:
                    self._report_exceeding_migrated(batch)
                    batch = []
        if batch:
            self._report_exceeding_migrated(batch)

    def _report_exceeding_migrated(self, pids_batch):
        """Report exceeding MigratedArticle PIDs via UnexpectedEvent."""
        UnexpectedEvent.create(
            e=Exception(
                "MigratedArticle PIDs not in classic website PID list"
            ),
            exc_traceback=None,
            detail={
                "task": self.TASK_NAME,
                "step": "exceeding_migrated_article",
                "collection": self.collection.acron,
                "total": len(pids_batch),
                "sample": pids_batch[:SAMPLE_SIZE],
            },
        )

    def _build_result(self):
        """Build the summary result dict."""
        return {
            "collection": self.collection.acron,
            "classic_website_total": len(self.current_pids),
            "migrated_total": self.matched_total + self.missing_total,
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
            self._process_pids()

            if not self.current_pids:
                logging.warning(
                    "No PIDs found from classic website for collection %s",
                    self.collection.acron,
                )
                return None

            self._detect_exceeding()
            result = self._build_result()

            logging.info(
                "PID tracking for %s: classic=%d, missing=%d, matched=%d, exceeding=%d",
                self.collection.acron,
                len(self.current_pids),
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
                    "collection": self.collection.acron
                    if self.collection
                    else None,
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
        user, collection, classic_website_config.pid_list_path, force_update
    )
    return tracker.run()
