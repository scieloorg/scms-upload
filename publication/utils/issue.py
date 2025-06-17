def build_issue(builder, bundle_id, issue, issue_pid):
    year = issue.publication_year
    volume = issue.volume
    number = issue.number
    supplement = issue.supplement
    if supplement == "":
        supplement = "0"

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
