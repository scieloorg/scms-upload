from lxml import etree


class XMLFormatError(Exception):
    def __init__(self, start_row, end_row, column, message):
        self.start_row = start_row
        self.end_row = end_row
        self.column = column
        self.message = message

    def __str__(self):
        return self.msg


def convert_xml_str_to_etree(xml_str):
    try:
        return etree.fromstring(xml_str)

    except etree.XMLSyntaxError as e:
        row, col = e.position
        msg = e.msg

        raise XMLFormatError(
            row=row,
            column=col,
            message=msg,
        )
