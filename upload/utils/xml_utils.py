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
        end_row, col = e.position
        msg = e.msg

        start_row = _extract_start_row_number(msg)

        raise XMLFormatError(
            start_row=start_row,
            end_row=end_row,
            column=col,
            message=msg,
        )


def get_snippet(xml_data, start_row, end_row):
    lines = []

    if not start_row:
        return lines

    if not end_row:
        end_row = start_row

    for line_number, content in numbered_lines(xml_data):
        if line_number >= start_row and line_number <= end_row:
            lines.append(content.encode())

    return lines
