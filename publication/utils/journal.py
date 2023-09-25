from migration.models import MigratedJournal
from scielo_classic_website.models.journal import Journal as ClassicJournal


def build_journal(scielo_journal, builder):
    journal_id = scielo_journal.scielo_issn
    migrated_journal_data = MigratedJournal.get(
        collection=scielo_journal.collection,
        pid=journal_id,
    ).data
    classic_j = ClassicJournal(migrated_journal_data)

    journal = scielo_journal.journal
    official_journal = journal.official_journal

    builder.add_ids(journal_id)
    builder.add_acron(scielo_journal.acron)
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
    # factory.add_event_to_timeline(status, since, reason)
    builder.add_journal_issns(
        scielo_issn=journal_id,
        eletronic_issn=official_journal.issn_electronic,
        print_issn=official_journal.issn_print,
    )
    builder.add_journal_titles(
        title=scielo_journal.title,
        title_iso=official_journal.title_iso,
        short_title=journal.short_title,
    )
    builder.add_logo_url(journal.logo_url or "https://www.scielo.org/journal_logo_missing.gif")
    builder.add_online_submission_url(classic_j.submission_url)
    # builder.add_related_journals(previous_journal, next_journal_title)
    for item in classic_j.sponsors:
        builder.add_sponsor(item)
    builder.add_thematic_scopes(
        subject_categories=None,
        subject_areas=classic_j.subject_areas,
    )
    builder.add_is_public()
