from dateutil.parser import parse


def parse_yyyymmdd(date):
    """
    Get year, month and day from date format which MM and DD can be 00
    """
    year, month, day = None, None, None
    try:
        _year = int(YYYYMMDD[:4])
        d = datetime(_year, 1, 1)
        year = _year

        _month = int(YYYYMMDD[4:6])
        d = datetime(year, _month, 1)
        month = _month

        _day = int(YYYYMMDD[6:])
        d = datetime(year, month, _day)
        day = _day

    except:
        pass

    return year, month, day


def parse_months_names(months_names):
    flexible_date = {}
    if months_names:
        months = months_names.split("/")
        flexible_date["initial_month_name"] = months[0]
        flexible_date["final_month_name"] = (
            months[-1] if months[-1] != months[0] else None
        )

    return flexible_date


def get_year_from_textual_date(date):
    """
    Get year from non standard textual date
    """
    # usa parse, mas só considera o ano pois não há garantia de que
    # reconheceu corretamente mês e dia, e o ano é o que mais interessa
    non_alpha = "".join([c for c in date if not c.isalpha()])
    for text in (date, non_alpha):
        try:
            parsed = parse(text)
            if str(parsed.year) in date:
                # na ausencia de ano, parse retorna o ano atual
                return parsed.year
        except:
            pass


def parse_non_standard_date(date):
    """
    Parse "incomplete" date which format is YYYYMMDD, and MM and DD can be 00,
    or textual date
    """
    if not date:
        return {}
    flexible_date = {}
    flexible_date["date_text"] = date

    if date.isdigit():
        year, month, day = parse_yyyymmdd(date)
        flexible_date["year"] = year
        flexible_date["month_number"] = month
        flexible_date["day"] = day
    else:
        flexible_date["year"] = get_year_from_textual_date(date)
    return flexible_date
