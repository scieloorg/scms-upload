class DBConnectError(Exception):
    ...


class PublishJournalError(Exception):
    ...


class PublishIssueError(Exception):
    ...


class PublishDocumentError(Exception):
    ...


class JournalPublicationForbiddenError(Exception):
    ...


class IssuePublicationForbiddenError(Exception):
    ...


class DocumentPublicationForbiddenError(Exception):
    ...
