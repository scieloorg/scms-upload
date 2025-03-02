def get_bundle_id(issn_id, year, volume=None, number=None, supplement=None):
    """
    Gera Id utilizado na ferramenta de migração para cadastro do documentsbundle.
    """

    if all(list(map(lambda x: x is None, [volume, number, supplement]))):
        return issn_id + "-aop"

    labels = ["issn_id", "year", "volume", "number", "supplement"]
    values = [issn_id, year, volume, number, supplement]

    data = dict([(label, value) for label, value in zip(labels, values)])

    labels = ["issn_id", "year"]
    _id = []
    for label in labels:
        value = data.get(label)
        if value:
            _id.append(str(value))

    labels = [("volume", "v"), ("number", "n"), ("supplement", "s")]
    for label, prefix in labels:
        value = data.get(label)
        if value is not None:
            # value pode ser igual a zero
            if value.isdigit():
                value = str(int(value))
            _id.append(prefix + value)

    return "-".join(_id)


def build_issue(builder, journal_id, issue, issue_pid):
    year = issue.publication_year
    volume = issue.volume
    number = issue.number
    supplement = issue.supplement
    if supplement == "":
        supplement = "0"

    bundle_id = get_bundle_id(
        issn_id=journal_id,
        year=year,
        volume=volume,
        number=number,
        supplement=supplement,
    )
    builder.add_ids(bundle_id)
    builder.add_dates(issue.created, issue.updated)
    builder.add_identification(volume, number, supplement)
    builder.add_order(order=int(issue.order))
    builder.add_pid(pid=issue_pid)
    builder.add_publication_date(year=year, start_month=None, end_month=None)
    # TODO obj_setter.has_docs(self)
    # builder.has_docs(documents)
    builder.identify_outdated_ahead()
    # builder.add_is_public()
    # builder.add_journal(journal_id)

    return builder.data
