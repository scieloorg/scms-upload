from scielo_classic_website.models.journal import Journal as ClassicJournal


def build_journal(journal_proc, builder):
    journal_id = journal_proc.pid
    migrated_journal_data = journal_proc.migrated_data.data
    classic_j = ClassicJournal(migrated_journal_data)

    journal = journal_proc.journal
    official_journal = journal.official_journal

    builder.add_ids(journal_id)
    builder.add_dates(journal_proc.created, journal_proc.updated)
    builder.add_acron(journal_proc.acron)
    builder.add_contact(
        name=", ".join(classic_j.publisher_name),
        email=classic_j.publisher_email,
        address=", ".join(classic_j.publisher_address),
        city=classic_j.publisher_city,
        state=classic_j.publisher_state,
        # TODO country name?
        country=classic_j.publisher_country,
    )

    # TODO
    # builder.add_issue_count(issue_count)
    # TODO
    # builder.add_metrics(total_h5_index, total_h5_median, h5_metric_year)
    for item in classic_j.mission:
        builder.add_mission(item["language"], item["text"])

    # TODO
    for item in classic_j.status_history:
        # FIXME ver os demais valores:
        # "interrupted": __("indexação interrompida pelo Comitê"),
        # "finished": __("publicação finalizada"),
        if item["status"] == "C":
            item["status"] = "current"
        elif item["status"] == "D":
            item["status"] = "deceased"
        elif item["status"] == "S":
            item["status"] = "suspended"

        builder.add_event_to_timeline(item["status"], item["date"], item.get("reason"))
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
    builder.add_logo_url(
        journal.logo_url or "https://www.scielo.org/journal_logo_missing.gif"
    )
    builder.add_online_submission_url(classic_j.submission_url)
    # TODO
    # builder.add_related_journals(previous_journal, next_journal_title)
    for item in classic_j.sponsors:
        builder.add_sponsor(item)
    builder.add_thematic_scopes(
        subject_categories=None,
        subject_areas=classic_j.subject_areas,
    )
    # builder.add_is_public()
