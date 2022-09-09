from django.utils.translation import gettext as _


RIT_ADDENDUM = 'addendum'
RIT_COMMENTARY_ARTICLE = 'commentary-article'
RIT_CORRECTED_ARTICLE = 'corrected-article'
RIT_LETTER = 'letter'
RIT_PARTIAL_RETRACTION = 'partial-retraction'
RIT_RETRACTED_ARTICLE = 'retracted-article'

RELATED_ITEM_TYPE = (
    (RIT_ADDENDUM, _('Addendum')),
    (RIT_COMMENTARY_ARTICLE, _('Commentary article')),
    (RIT_CORRECTED_ARTICLE, _('Corrected article')),
    (RIT_LETTER, _('Letter')),
    (RIT_PARTIAL_RETRACTION, _('Partial retraction')),
    (RIT_RETRACTED_ARTICLE, _('Retracted article')),
)
