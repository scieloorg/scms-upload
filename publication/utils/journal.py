import logging


def build_journal(
    builder, journal, journal_id, journal_acron, journal_history, availability_status
):
    official_journal = journal.official_journal
    builder.add_issue_count(journal.issue_count)
    builder.add_ids(journal_id)
    builder.add_dates(journal.created, journal.updated)
    builder.add_acron(journal_acron)

    builder.add_contact(**journal.contact)

    for mission in journal.mission.all():
        builder.add_mission(mission.language.code2, mission.text)

    for jh in journal_history.all():
        builder.add_event_to_timeline(
            jh.event_type,
            jh.date,
            jh.interruption_reason,
        )

    current_status = "inprogress"
    if builder.data.get("status_history"):
        try:
            current_status = sorted(
                builder.data["status_history"], key=lambda x: x["date"]
            )[-1]["status"]
        except (IndexError, KeyError):
            current_status = "inprogress"
    builder.data["current_status"] = current_status

    builder.add_journal_issns(
        scielo_issn=journal_id,
        eletronic_issn=official_journal.issn_electronic,
        print_issn=official_journal.issn_print,
    )
    builder.add_journal_titles(
        title=journal.title or official_journal.title,
        title_iso=official_journal.title_iso,
        short_title=journal.short_title,
    )
    try:
        # FIXME
        builder.add_logo_url(
            journal.logo_url or "https://www.scielo.org/journal_logo_missing.gif"
        )
    except AttributeError:
        builder.add_logo_url("https://www.scielo.org/journal_logo_missing.gif")
    builder.add_online_submission_url(journal.submission_online_url)  # Adicionar
    builder.add_related_journals(
        previous_journal=journal.official_journal.previous_journal_title,
        next_journal_title=journal.official_journal.next_journal_title,
    )
    for sponsor in journal.sponsor.all():
        builder.add_sponsor(sponsor.institution.name)

    names = set()
    for item in journal.owner.all():
        name = item.institution.name
        if not name:
            continue
        names.add(name)
    for item in journal.publisher.all():
        name = item.institution.name
        if not name:
            continue
        names.add(name)

    for name in names:
        builder.add_publisher(name)

    builder.add_thematic_scopes(
        subject_categories=journal.wos_areas,
        subject_areas=journal.subject_areas,
    )
    builder.add_is_public(availability_status)
