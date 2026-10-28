import logging


class ReferenceIndexRoutineFilter(logging.Filter):
    """Hide routine reference-index task messages, never warnings or failures."""

    def filter(self, record):
        if record.levelno >= logging.WARNING:
            return True
        return (
            "path=wagtail.tasks.update_reference_index_task"
            not in record.getMessage().split()
        )
