class GetOrCreateOfficialJournalError(Exception):
    ...


class JournalProcUpdateError(Exception):
    ...


class MissionGetError(Exception):
    ...


class MissionCreateOrUpdateError(Exception):
    ...


class SubjectCreationOrUpdateError(Exception):
    def __init__(self, code, message):
        super().__init__(
            f"Unable to create or update Subject with code: {code}: {str(message)}"
        )