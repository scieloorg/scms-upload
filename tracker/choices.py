from django.utils.translation import gettext_lazy as _

TASK_TRACK_STATUS_STARTED = "started"
TASK_TRACK_STATUS_INTERRUPTED = "interrupted"
TASK_TRACK_STATUS_FINISHED = "finished"

TASK_TRACK_STATUS = (
    (TASK_TRACK_STATUS_STARTED, _("started")),
    (TASK_TRACK_STATUS_INTERRUPTED, _("interrupted")),
    (TASK_TRACK_STATUS_FINISHED, _("finished")),
)

ERROR = "ERROR"
EXCEPTION = "EXCEPTION"
INFO = "INFO"
WARNING = "WARNING"

EVENT_MSG_TYPE = [
    (ERROR, _("error")),
    (WARNING, _("warning")),
    (INFO, _("info")),
    (EXCEPTION, _("exception")),
]


PROGRESS_STATUS_IGNORED = "IGNORED"
PROGRESS_STATUS_REPROC = "REPROC"
PROGRESS_STATUS_TODO = "TODO"
PROGRESS_STATUS_DOING = "DOING"
PROGRESS_STATUS_DONE = "DONE"
PROGRESS_STATUS_PENDING = "PENDING"
PROGRESS_STATUS_BLOCKED = "BLOCKED"

PROGRESS_STATUS = (
    (PROGRESS_STATUS_REPROC, _("To reprocess")),
    (PROGRESS_STATUS_TODO, _("To do")),
    (PROGRESS_STATUS_DONE, _("Done")),
    (PROGRESS_STATUS_DOING, _("Doing")),
    (PROGRESS_STATUS_BLOCKED, _("Blocked")),
    (PROGRESS_STATUS_PENDING, _("Pending")),
    (PROGRESS_STATUS_IGNORED, _("ignored")),
)

PROGRESS_STATUS_FORCE_UPDATE = [
    PROGRESS_STATUS_REPROC,
    PROGRESS_STATUS_TODO,
    PROGRESS_STATUS_DONE,
    PROGRESS_STATUS_PENDING,
    PROGRESS_STATUS_BLOCKED,
]

PROGRESS_STATUS_REGULAR_TODO = [
    PROGRESS_STATUS_REPROC,
    PROGRESS_STATUS_TODO,
]

PROGRESS_STATUS_RETRY = [
    PROGRESS_STATUS_PENDING,
    PROGRESS_STATUS_BLOCKED,
]

VALID_STATUS = PROGRESS_STATUS_FORCE_UPDATE + [PROGRESS_STATUS_DOING]


def get_valid_status(status, force_update):
    """
    Retorna a lista de status a considerar no filtro de itens a processar.

    - Se `status` for informado, verifica se os valores são válidos.
    - Se `force_update` for True, retorna PROGRESS_STATUS_FORCE_UPDATE
      (todos os status exceto DOING e IGNORED), permitindo reprocessar
      inclusive itens já concluídos (DONE).
    - Caso contrário, retorna PROGRESS_STATUS_REGULAR_TODO (REPROC + TODO),
      processando apenas itens que ainda não foram concluídos.
    """
    if status:
        status_list = set()
        if isinstance(status, str):
            status_list.add(status)
        elif isinstance(status, list):
            status_list.update(status)
        status_list = list(status_list & set(VALID_STATUS))
        if status_list:
            return status_list
    if force_update:
        return PROGRESS_STATUS_FORCE_UPDATE
    return PROGRESS_STATUS_REGULAR_TODO


def allowed_to_run(status, force_update):
    """
    Indica se um item com o `status` dado pode ser executado.

    - Permite executar itens com status DOING apenas quando `force_update`
      é True (evita execuções concorrentes em condições normais).
    - Permite executar itens cujo status está em PROGRESS_STATUS_FORCE_UPDATE
      quando `force_update` é True, ou em PROGRESS_STATUS_REGULAR_TODO
      independentemente de `force_update`.
    """
    if force_update and status == PROGRESS_STATUS_DOING:
        return True
    return (
        force_update
        and status in PROGRESS_STATUS_FORCE_UPDATE
        or status in PROGRESS_STATUS_REGULAR_TODO
    )
