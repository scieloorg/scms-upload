from . import exceptions


def fetch_record(_id, model, **kwargs):
    try:
        obj = model.objects(_id=_id, **kwargs)[0]
    except IndexError:
        return None
    except Exception as e:
        raise exceptions.FetchRecordError(e)
    else:
        return obj

