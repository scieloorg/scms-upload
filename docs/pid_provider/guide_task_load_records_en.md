# Guide: Loading Records from counter_dict

## Purpose

The `task_load_records_from_counter_dict` task collects XML documents from a
specific SciELO collection via the OPAC `counter_dict` API endpoint and loads
them into the system.

The records harvested from the OPAC already contain an assigned **PID v3**
identifier. For this reason, the data source **must** be the official SciELO
website (e.g., `https://www.scielo.br`). Using any other source could result in
the creation of unprecedented PID v3 identifiers that do not correspond to
published articles, which would compromise data integrity.

**What it does:**

1. Connects to the OPAC API (e.g., `https://www.scielo.br/api/v1/counter_dict`)
2. Retrieves document metadata from the specified collection and date range
3. For each document found, dispatches a subtask (`task_load_record_from_xml_url`)
   that downloads the XML and creates or updates records in **PidProviderXML** and **XMLURL**

> **Important:** This task **only** creates or updates `PidProviderXML` and
> `XMLURL` records. It does **not** create `Article` records.

---

## Creating a Periodic Task via Django Admin

### Step 1: Access Django Admin

1. Open your browser and navigate to the Django admin panel:
   `https://<your-domain>/admin/`
2. Log in with a superuser account

### Step 2: Navigate to Periodic Tasks

1. In the Django admin sidebar or main page, locate the section
   **PERIODIC TASKS** (provided by `django_celery_beat`)
2. Click on **Periodic tasks**
3. Click the **Add periodic task** button (top right)

### Step 3: Configure the Task

Fill in the following fields:

- **Name**: A descriptive name, e.g.,
  `Load OPAC records - Brazil (scl)`
- **Task (registered)**: Select or type:
  `pid_provider.tasks.task_load_records_from_counter_dict`
- **Enabled**: Check this box to activate the task
- **Schedule**: Choose one of the available schedule types:
  - **Interval**: e.g., every 24 hours
  - **Crontab**: e.g., `0 2 * * *` (every day at 2:00 AM)
  - **One-off task**: Check this if the task should run only once

### Step 4: Configure Keyword Arguments (kwargs)

In the **Keyword arguments** field (JSON format), enter the task parameters:

```json
{
  "username": "admin",
  "collection_acron": "scl",
  "from_date": "2024-01-01",
  "until_date": "2024-12-31",
  "limit": 100,
  "timeout": 5,
  "force_update": false,
  "opac_domain": "https://www.scielo.br"
}
```

### Step 5: Save

Click **Save** to create the periodic task. The Celery Beat scheduler will
pick it up according to the configured schedule.

---

## Parameter Reference

| Parameter | Type | Default | Description |
|---|---|---|---|
| `username` | str | `None` | Username of the user running the task. |
| `user_id` | int | `None` | User ID (alternative to `username`). |
| `collection_acron` | str | `"scl"` | Collection acronym (e.g., `"scl"` for Brazil). |
| `from_date` | str | `"2000-01-01"` | Start date in ISO format (`YYYY-MM-DD`). |
| `until_date` | str | today | End date in ISO format (`YYYY-MM-DD`). |
| `limit` | int | `100` | Number of documents per API page. |
| `timeout` | int | `5` | HTTP request timeout in seconds. |
| `force_update` | bool | `false` | Force update even if the record already exists. |
| `opac_domain` | str | `"www.scielo.br"` | OPAC domain to harvest from. **Must include the protocol** (e.g., `https://www.scielo.br`). Using `https://` ensures a secure connection to the official SciELO website. If the protocol is omitted, the system defaults to `http://`. |

---

## Verifying Results

After the task completes, verify the results by checking the
`PidProviderXML` and `XMLURL` models.

### Checking PidProviderXML Records

In the Django admin, navigate to **PID PROVIDER > PidProviderXML** to see the
created or updated records.

Alternatively, use the Django shell:

```python
from pid_provider.models import PidProviderXML

# List recent records
recent = PidProviderXML.objects.order_by("-updated")[:20]
for record in recent:
    print(f"PID v3: {record.v3} | Status: {record.proc_status} | "
          f"Updated: {record.updated}")

# Filter by collection
from collection.models import Collection
col = Collection.objects.get(acron="scl")
records = PidProviderXML.objects.filter(collections=col)
print(f"Total records for 'scl': {records.count()}")
```

### Checking XMLURL Records

In the Django admin, navigate to **PID PROVIDER > XMLURL** to see the
URL processing status.

```python
from pid_provider.models import XMLURL

# List recent XMLURL records
recent_urls = XMLURL.objects.order_by("-updated")[:20]
for url_record in recent_urls:
    print(f"URL: {url_record.url} | Status: {url_record.status} | "
          f"PID: {url_record.pid}")

# Check for failed URLs
failed = XMLURL.objects.exclude(status="").exclude(exceptions="")
print(f"URLs with errors: {failed.count()}")
```

---

## Troubleshooting

Issues are categorized by criticality level:

- 🔴 **CRITICAL** — Prevents task execution entirely; must be resolved immediately
- 🟡 **MODERATE** — Task runs but produces incomplete or incorrect results
- 🟢 **LOW** — Minor issues that do not affect core functionality

| Level | Problem | Solution |
|---|---|---|
| 🔴 | Celery worker is not running | Start the Celery worker: `celery -A config worker -l info`. Without a running worker, no tasks will be processed. |
| 🔴 | Celery Beat scheduler is not running | Start Celery Beat: `celery -A config beat -l info`. Without Beat, periodic tasks will not be dispatched. |
| 🔴 | Connection to OPAC API fails (network/DNS error) | Verify that the `opac_domain` is reachable and includes `https://`. Check firewall rules and DNS resolution. Review `UnexpectedEvent` records for error details. |
| 🟡 | No records appear after task execution | Check that `from_date` and `until_date` cover a range with published documents. Verify the `collection_acron` is correct. Review Celery worker logs for warnings. |
| 🟡 | Records exist but are not updated | Set `force_update` to `true` in the kwargs to force reprocessing of existing records. |
| 🟡 | XMLURL records show error status | Check the `exceptions` field in `XMLURL` for details. Common causes include invalid XML URLs or temporary server errors. The records will be retried in future runs. |
| 🟢 | Task runs slowly | Reduce the `limit` parameter to process fewer documents per page, or increase `timeout` if the OPAC API is slow. This does not affect data correctness. |
| 🟢 | Some documents are skipped with warnings | Documents without a valid `journal_acronym` are skipped. Check Celery worker logs for `WARNING` messages. These are typically incomplete records in the OPAC API. |

### Checking Error Logs

Errors are recorded in the `UnexpectedEvent` model:

```python
from tracker.models import UnexpectedEvent

errors = UnexpectedEvent.objects.filter(
    detail__task="task_load_records_from_counter_dict"
).order_by("-created")[:10]

for error in errors:
    print(f"Date: {error.created}")
    print(f"Exception: {error.exception}")
    print(f"Details: {error.detail}")
    print("---")
```
