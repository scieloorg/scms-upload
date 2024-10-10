from django.utils.translation import gettext as _


def validate_rendition(rendition, xml_with_pre):
    """
    Arguments
    ---------
    xml_with_pre : XMLWithPre
    rendition : dict {
                "name": "1234-1234-acron-45-1-1.pdf',
                "lang": "en",
                "component_type": "rendition",
                "main": "en",
                "content": b'',
            }

    Returns
    -------
    Generator of validation result
    """
    for item in absent_xml_data_in_rendition(rendition, xml_with_pre):
        yield {
            "message": _("It was expected to find `{}` in {} ({})").format(
                item, rendition['name'], rendition['lang']
            )
        }

    for item in absent_pdf_words_in_xml_data(rendition, xml_with_pre):
        yield {
            "message": _("It was expected to find `{}` in XML ({})").format(
                item, rendition['lang']
            )
        }


def absent_xml_data_in_rendition(rendition, xml_with_pre):
    """
    Retorna itens (str) presentes no XML e não encontrados no PDF

    Arguments
    ---------
    xml_with_pre : XMLWithPre
    rendition : dict {
                "name": "1234-1234-acron-45-1-1.pdf',
                "lang": "en",
                "component_type": "rendition",
                "main": "en",
                "content": b'',
            }

    Returns
    -------
    Gerador de textos faltantes no PDF
    """
    # TODO
    # lembrar de considerar o idioma ao comparar:
    # selecionar os dados do idioma de acordo com o idioma do PDF
    # lembrar de considerar que os dados não associados ao idioma
    # tem que ser encontrados em todos os PDFs
    pass


def absent_pdf_words_in_xml_data(rendition, xml_with_pre):
    """
    Retorna itens (str) presentes no PDF e não encontrados no XML

    Arguments
    ---------
    xml_with_pre : XMLWithPre
    rendition : dict {
                "name": "1234-1234-acron-45-1-1.pdf',
                "lang": "en",
                "component_type": "rendition",
                "main": "en",
                "content": b'',
            }

    Returns
    -------
    Gerador de textos faltantes no XML
    """
    pass
