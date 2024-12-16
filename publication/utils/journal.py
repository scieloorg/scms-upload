def build_journal(builder, journal, journal_id, journal_acron, journal_history, availability_status):
    official_journal = journal.official_journal

    builder.add_ids(journal_id)
    builder.add_dates(journal.created, journal.updated)
    builder.add_acron(journal_acron)

    builder.add_contact(**journal.contact)

    for mission in journal.mission.all():
        builder.add_mission(mission.language.code2, mission.text)

    for journal_history in journal_history.all():
        if journal_history.event_type == "ADMITTED":
            event_type = "current"
        elif journal_history.interruption_reason == "ceased":
            # deceased está incorreto no opac
            event_type = "deceased"
        elif journal_history.interruption_reason == "suspended-by-committee":
            event_type = "suspended"
        elif journal_history.interruption_reason == "suspended-by-editor":
            event_type = "suspended"
        elif journal_history.interruption_reason == "not-open-access":
            event_type = "suspended"
        else:
            event_type = "inprogress"

        builder.add_event_to_timeline(
            event_type,
            journal_history.date,
            journal_history.interruption_reason,
        )
    current_status = "inprogress"
    if builder.data.get("status_history"):
        try:
            current_status = sorted(builder.data["status_history"], key=lambda x: x['date'])[-1]["status"]
        except IndexError:
            current_status = None
        if current_status == "current" and availability_status != "C":
            current_status = "inprogress"
        elif current_status != "current":
            current_status = "no-current"
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
        builder.add_logo_url(journal.logo_url or "https://www.scielo.org/journal_logo_missing.gif")
    except AttributeError:
        builder.add_logo_url("https://www.scielo.org/journal_logo_missing.gif")
    builder.add_online_submission_url(journal.submission_online_url)  # Adicionar
    builder.add_related_journals(
        previous_journal=journal.official_journal.previous_journal_title,
        next_journal_title=journal.official_journal.next_journal_title,
    )
    for sponsor in journal.sponsor.all():
        builder.add_sponsor(sponsor.institution.name)

    names = []
    for item in journal.owner.all():
        name = item.institution.name
        if name not in names:
            names.append(name)
            builder.add_publisher(name)
    for item in journal.publisher.all():
        name = item.institution.name
        if name not in names:
            names.append(name)
            builder.add_publisher(name)

    builder.add_thematic_scopes(
        subject_categories=None,
        subject_areas=journal.subject_areas,
    )
    builder.add_is_public(availability_status)
