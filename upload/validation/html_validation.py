from django.utils.translation import gettext as _


def validate_webpage(web_page, xml_with_pre):
    """
    Arguments
    ---------
    xml_with_pre : XMLWithPre
    web_page : dict {
                "lang": "en",
                "url": "url",
            }

    Returns
    -------
    Generator of validation result
    """
    # web_page['url'] can be None

    if not web_page["url"]:
        yield {
            "message": _("Web page `{}` does not exist").format(
                web_page['lang']
            )
        }

    for item in absent_xml_data_in_web_page(web_page, xml_with_pre):
        yield {
            "message": _("It was expected to find `{}` in {} ({})").format(
                item, web_page['url'], web_page['lang']
            )
        }


def absent_xml_data_in_web_page(web_page, xml_with_pre):
    """
    Retorna itens (str) presentes no XML e não encontrados no web page

    Arguments
    ---------
    xml_with_pre : XMLWithPre
    web_page : dict {
                "name": "1234-1234-acron-45-1-1.pdf',
                "lang": "en",
                "component_type": "web_page",
                "main": "en",
                "content": b'',
            }

    Returns
    -------
    Gerador de textos faltantes no web page
    """
    # TODO
    # lembrar de considerar o idioma ao comparar:
    # selecionar os dados do idioma de acordo com o idioma do web page
    # lembrar de considerar que os dados não associados ao idioma
    # tem que ser encontrados em todos os web pages
    pass
