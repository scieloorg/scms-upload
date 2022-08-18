class DBConnectError(Exception):
    ...


class FetchRecordError(Exception):
    ...


class JournalDataError(Exception):
    ...


class JournalSaveError(Exception):
    ...


class IssueDataError(Exception):
    ...


class IssueSaveError(Exception):
    ...


class DocumentDataError(Exception):
    ...


class DocumentSaveError(Exception):
    ...


class PublishJournalError(Exception):
    ...


class MigratedJournalSaveError(Exception):
    ...


class JournalMigrationTrackSaveError(Exception):
    ...