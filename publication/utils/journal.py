from datetime import datetime


def build_journal(journal_proc, builder):
    journal_id = journal_proc.pid
    migrated_journal_data = journal_proc.migrated_data.data

    journal = journal_proc.journal
    official_journal = journal.official_journal

    builder.add_ids(journal_id)
    builder.add_dates(journal_proc.created, journal_proc.updated)
    builder.add_acron(journal_proc.acron)
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
        # builder.add_event_to_timeline(item["status"], item["date"], item.get("reason"))
    for journal_history in journal.journal_history.all():
        builder.add_event_to_timeline(
            journal_history.opac_event_type,
            journal_history.date,
            journal_history.interruption_reason,
        )
    builder.add_journal_issns(
        scielo_issn=journal_id,
        eletronic_issn=official_journal.issn_electronic,
        print_issn=official_journal.issn_print,
    )
    builder.add_journal_titles(
        title=journal_proc.title,
        title_iso=official_journal.title_iso,
        short_title=journal.short_title,
    )
    try:
        # FIXME
        builder.add_logo_url(journal.logo_url)
    except AttributeError:
        builder.add_logo_url("https://www.scielo.org/journal_logo_missing.gif")
    
    builder.add_online_submission_url(journal.submission_online_url) #Adicionar
    # TODO
    # builder.add_related_journals(previous_journal, next_journal_title)
    for sponsor in journal.sponsor.all(): #Adicionar
        builder.add_sponsor(sponsor.institution.name)
    
    for subject_area in journal.subject.all():
        builder.add_thematic_scopes(
            subject_categories=None,
            subject_areas=subject_area.value,
        )
    # builder.add_is_public()
