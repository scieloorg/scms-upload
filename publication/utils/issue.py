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
        if value:
            if value.isdigit():
                value = str(int(value))
            _id.append(prefix + value)

    return "-".join(_id)


def build_issue(scielo_issue, journal_id, builder):
    issue = scielo_issue.issue
    year = issue.publication_year
    volume = issue.volume
    number = issue.number
    supplement = issue.supplement

    issue_id = get_bundle_id(
        issn_id=journal_id,
        year=year,
        volume=volume,
        number=number,
        supplement=supplement,
    )
    builder.add_ids(issue_id)
    builder.add_identification(volume, number, supplement)
    builder.add_order(order=scielo_issue.issue_pid[-5:])
    builder.add_pid(pid=scielo_issue.issue_pid)
    builder.add_publication_date(year=year, start_month=None, end_month=None)
    # TODO obj_setter.has_docs(self)
    # builder.has_docs(documents)
    builder.identify_outdated_ahead()
    builder.add_issue_type()
    builder.add_is_public()
    builder.add_journal(journal_id)

    return builder.data
