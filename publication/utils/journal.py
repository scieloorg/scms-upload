def build_journal(builder, journal, journal_id, journal_acron, journal_history):
    official_journal = journal.official_journal

    builder.add_ids(journal_id)
    builder.add_dates(journal.created, journal.updated)
    builder.add_acron(journal_acron)
    for publisher in journal.publisher.all():
        builder.add_contact(
            name=publisher.institution.name,
            address=publisher.institution.location,
            city=publisher.institution.location.city.name,
            state=publisher.institution.location.state.name,
            country=publisher.institution.location.country.name,
        )

    for mission in journal.mission.all():
        builder.add_mission(mission.language, mission.text)

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
        builder.add_logo_url(journal.logo_url)
    except AttributeError:
        builder.add_logo_url("https://www.scielo.org/journal_logo_missing.gif")
    builder.add_online_submission_url(journal.submission_online_url)  # Adicionar
    # TODO
    # builder.add_related_journals(previous_journal, next_journal_title)
    for sponsor in journal.sponsor.all():
        builder.add_sponsor(sponsor.institution.name)
    for subject_area in journal.subject.all():
        builder.add_thematic_scopes(
            subject_categories=None,
            subject_areas=subject_area.value,
        )

    # builder.add_is_public()
