class ArticleProcUpdateError(Exception): ...


class JournalProcUpdateError(Exception): ...


class IssueProcUpdateError(Exception): ...


"""
Exceções customizadas do módulo proc.
"""


class ProcBaseException(Exception):
    """Exceção base para o módulo proc."""
    pass


# Exceções compartilhadas que podem ser usadas por múltiplos módulos
class UnableToCreateIssueProcsError(ProcBaseException):
    """Erro ao criar IssueProcs."""
    pass