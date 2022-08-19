from lxml import etree

from .file_utils import numbered_lines

import re


PATTERN_START_END_LINE_NUMBERS = r'.* line (?P<start>\d*) and .*, line (?P<end>\d*),'
PATTERN_START_LINE_NUMBER = r'.* line (?P<start>\d*),'


class XMLFormatError(Exception):
    def __init__(self, start_row, end_row, column, message):
        self.start_row = start_row
        self.end_row = end_row
        self.column = column
        self.message = message

    def __str__(self):
        return self.message


def _extract_start_row_number(message):
    for ptn in [
        PATTERN_START_END_LINE_NUMBERS,
        PATTERN_START_LINE_NUMBER,
    ]:
        match = re.search(ptn, message)
        if match and 'start' in match.groupdict():
            return int(match.groupdict()['start'])


def get_etree_from_xml_content(xml_str):
    try:
        return etree.fromstring(xml_str)

    except etree.XMLSyntaxError as e:
        end_row, col = e.position
        message = e.msg

        start_row = _extract_start_row_number(message)

        raise XMLFormatError(
            start_row=start_row,
            end_row=end_row,
            column=col,
            message=message,
        )


def get_snippet(xml_data, start_row, end_row):
    lines = []

    if not start_row:
        return lines

    if not end_row:
        end_row = start_row

    for line_number, content in numbered_lines(xml_data):
        if line_number >= start_row and line_number <= end_row:
            try:
                decode_content = content.decode()
            except AttributeError:
                decode_content = content

            lines.append(decode_content)

    return lines
