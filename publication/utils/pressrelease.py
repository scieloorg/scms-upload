def build_pressrelease(pressrelease, builder):
    builder.add_journal_title(pressrelease.journalproc_set.first().pid)
    builder.add_title_pressreleaase(pressrelease.title)
    builder.add_language(pressrelease.language.code2)
    builder.add_doi(pressrelease.doi)
    builder.add_content(pressrelease.content)
    builder.add_url(pressrelease.url)
    builder.add_media_content(pressrelease.media_content)
    builder.add_publication_data(pressrelease.publication_data)
    return builder.data