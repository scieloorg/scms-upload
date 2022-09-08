from django.utils.translation import gettext as _


FUNDER = 'FUNDER'
SCHOLARLY = 'SCHOLARLY'
PRIVATE = 'PRIVATE'
GOVERNMENT = 'GOVERNMENT'
NON_PROFIT = 'NON_PROFIT'
SOCIETY = 'SOCIETY'
OTHER = 'OTHER'

inst_type = (
    ('', ''),
    (FUNDER, _('agência de apoio à pesquisa')),
    (SCHOLARLY, _('universidade e instâncias ligadas à universidades')),
    (GOVERNMENT, _('empresa ou instituto ligadas ao governo')),
    (PRIVATE, _('organização privada')),
    (NON_PROFIT, _('organização sem fins de lucros')),
    (SOCIETY, _('sociedade científica, associação pós-graduação, associação profissional')),
    (OTHER, _('outros')),
)
