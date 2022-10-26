class SiteDatabaseIsUnavailableError(Exception):
    ...


class PIDv3DoesNotExistInSiteDatabase(Exception):
    ...


class XMLUriIsUnavailableError(Exception):
    def __init__(self, uri):
        self.uri = uri
