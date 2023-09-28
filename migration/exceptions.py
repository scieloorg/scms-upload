class CreateOrUpdateMigratedError(Exception):
    ...


class ScheduleMigrationsError(Exception):
    ...


class GetOrCreateCrontabScheduleError(Exception):
    ...


class CreateOrUpdateMigratedFileError(Exception):
    ...


class CreateOrUpdateMigratedJournalError(Exception):
    ...


class CreateOrUpdateMigratedIssueError(Exception):
    ...


class CreateOrUpdateMigratedDocumentError(Exception):
    ...


class CreateOrUpdateBodyAndBackFileError(Exception):
    ...


class CreateOrUpdateGeneratedXMLFileError(Exception):
    ...


class MigratedXMLFileNotFoundError(Exception):
    ...
