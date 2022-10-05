from datetime import datetime

from core.models import FlexibleDate


def get_flexible_date(date):
    try:
        flexible_date = FlexibleDate()
        flexible_date.text = date
        try:
            year = int(date[:4])
            d = datetime(year, 1, 1)
            flexible_date.year = year

            month = int(date[4:6])
            d = datetime(year, month, 1)
            flexible_date.month = month

            day = int(date[6:])
            d = datetime(year, month, day)
            flexible_date.day = day

        except:
            pass
        flexible_date.save()
    except:
        return None
    return flexible_date
